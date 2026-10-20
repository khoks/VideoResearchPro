"""Saved searches: a pinned library question, re-asked on a schedule (S-8.3.2 / M3).

Plan: docs/plans/m3-saved-searches-alerts.md. A saved search is a
``saved_searches`` row (what to ask, over which scope) plus one
``scheduled_runs`` row of kind ``saved_search`` (when), written together.
The scope is the library-question scope of S-8.1.4 (``app/schemas/qa_scope.py``),
stored and resolved through ``qa_scope_service`` so a shelf means the same
documents here as in its list and its own Q&A (D-083).
The scheduler tick (S-8.3.1) dispatches ``saved_search.run`` with the saved
search's id; ``execute`` is what that task, and "Run now", call.

A run is a library Q&A exchange like any other: quota enforced before it
and recorded after it succeeds (D-045), the tenant's visible set (narrowed
to a shelf's documents when scoped), corpus statistics and trust weights
as the library route passes them, BYOK context, the exchange stored in
``library_qa_exchanges`` and indexed in ``qa_library_global``. What a run
adds is the baseline on the saved search (``last_*``) that the change
detector (S-8.3.3) compares the next run with. A run that fails leaves that
baseline untouched.

Every run is recorded on the row (``last_run_at`` / ``last_status`` /
``last_error``), including the ones that never reach the model: a tenant
over quota, a tier that lost the feature, a shelf that was deleted.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.library_qa_exchange import LibraryQAExchange
from app.models.saved_search import SavedSearch
from app.models.user import User
from app.services import qa_scope_service, scheduler_service, tier_service

logger = logging.getLogger(__name__)

KIND = "saved_search"
FEATURE = "saved_searches"
CAP_KEY = "saved_searches_active_cap"
QUOTA_RESOURCE = "library_qa_exchanges"
MAX_QUESTION_CHARS = 2000

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_QUOTA = "quota_exceeded"
STATUS_FEATURE = "feature_unavailable"
STATUS_SCOPE_MISSING = "scope_missing"
STATUS_DISABLED = "disabled"
STATUS_MISSING = "missing"
STATUSES = (STATUS_OK, STATUS_FAILED, STATUS_QUOTA, STATUS_FEATURE, STATUS_SCOPE_MISSING)

#: The cadence presets a person can pick (S-8.3.1 also accepts `every`, which
#: is for system kinds; a saved search is never re-asked every N seconds).
USER_CADENCES = ("daily", "weekly", "monthly")


class SavedSearchError(ValueError):
    """A request that cannot be saved as given (422)."""


class CapReached(RuntimeError):
    """The tier's cap on active saved searches is reached (409)."""


# The scope names a shelf the caller does not own, or that no longer exists (404).
ScopeNotFound = qa_scope_service.ScopeNotFound


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Validation


def active_cap(user: User) -> int:
    """How many enabled saved searches this tier may hold (-1 unlimited)."""
    return int(tier_service.capabilities_for(user).get(CAP_KEY, 0))


def active_count(db: Session, tenant_id: str, *, excluding: str | None = None) -> int:
    q = db.query(SavedSearch.id).filter(SavedSearch.tenant_id == tenant_id, SavedSearch.enabled.is_(True))
    if excluding:
        q = q.filter(SavedSearch.id != excluding)
    return q.count()


def _check_cap(db: Session, user: User, *, excluding: str | None = None) -> None:
    cap = active_cap(user)
    if cap == -1:
        return
    if active_count(db, user.id, excluding=excluding) >= cap:
        raise CapReached(
            f"Your plan keeps up to {cap} active saved searches. Pause or delete one first."
            if cap
            else "Your plan does not include saved searches."
        )


def _clean_question(question: str) -> str:
    q = " ".join((question or "").split())
    if len(q) < 3:
        raise SavedSearchError("The question needs at least three characters.")
    if len(q) > MAX_QUESTION_CHARS:
        raise SavedSearchError(f"The question is longer than {MAX_QUESTION_CHARS} characters.")
    return q


def normalise_scope(db: Session, tenant_id: str, scope: dict | None) -> dict | None:
    """The narrowing part of a library-question scope (``None`` = the whole
    library), checked by resolving it: a key the resolver does not know is a
    422 (ignoring it would widen the question), someone else's shelf a 404."""
    keys = qa_scope_service.narrowing(scope)
    if not keys:
        return None
    try:
        qa_scope_service.resolve_document_ids(db, tenant_id, keys)
    except qa_scope_service.UnknownScopeKey as e:
        raise SavedSearchError(str(e)) from None
    return keys


def normalise_user_cadence(cadence: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(cadence, dict) or cadence.get("cadence") not in USER_CADENCES:
        raise SavedSearchError(f"cadence must be one of {', '.join(USER_CADENCES)}.")
    try:
        return scheduler_service.normalise_cadence(cadence)
    except scheduler_service.CadenceError as e:
        raise SavedSearchError(str(e)) from None


def _load_scope(ss: SavedSearch) -> dict | None:
    scope = qa_scope_service.load(ss.scope_json)
    return qa_scope_service.narrowing(scope) or None


# ---------------------------------------------------------------------------
# CRUD


def create(
    db: Session,
    user: User,
    *,
    question: str,
    cadence: dict[str, Any],
    answer_language: str = "en",
    scope: dict | None = None,
    notify_email: bool = True,
) -> SavedSearch:
    canonical = normalise_user_cadence(cadence)
    clean_scope = normalise_scope(db, user.id, scope)
    q = _clean_question(question)
    _check_cap(db, user)
    ss = SavedSearch(
        tenant_id=user.id,
        question=q,
        answer_language=(answer_language or "en")[:10],
        scope_json=qa_scope_service.dump(clean_scope),
        notify_email=bool(notify_email),
        enabled=True,
    )
    db.add(ss)
    db.flush()
    scheduler_service.schedule(db, kind=KIND, target_id=ss.id, cadence=canonical, tenant_id=user.id)
    db.refresh(ss)
    return ss


def list_for(db: Session, tenant_id: str) -> list[SavedSearch]:
    return (
        db.query(SavedSearch)
        .filter(SavedSearch.tenant_id == tenant_id)
        .order_by(SavedSearch.created_at.desc())
        .all()
    )


def get_for(db: Session, tenant_id: str, saved_search_id: str) -> SavedSearch | None:
    return (
        db.query(SavedSearch)
        .filter(SavedSearch.id == saved_search_id, SavedSearch.tenant_id == tenant_id)
        .first()
    )


_UNSET: Any = object()


def update(
    db: Session,
    user: User,
    ss: SavedSearch,
    *,
    question: str | None = None,
    cadence: dict[str, Any] | None = None,
    answer_language: str | None = None,
    scope: Any = _UNSET,
    notify_email: bool | None = None,
    enabled: bool | None = None,
) -> SavedSearch:
    if question is not None:
        ss.question = _clean_question(question)
    if answer_language is not None:
        ss.answer_language = answer_language[:10] or "en"
    if scope is not _UNSET:
        ss.scope_json = qa_scope_service.dump(normalise_scope(db, user.id, scope))
    if notify_email is not None:
        ss.notify_email = bool(notify_email)
    if enabled is True and not ss.enabled:
        _check_cap(db, user, excluding=ss.id)
    if cadence is not None:
        canonical = normalise_user_cadence(cadence)
        scheduler_service.schedule(
            db, kind=KIND, target_id=ss.id, cadence=canonical, tenant_id=user.id,
            enabled=ss.enabled if enabled is None else enabled,
        )
    if enabled is not None and enabled != ss.enabled:
        ss.enabled = enabled
        scheduler_service.set_enabled(db, KIND, ss.id, enabled)
    db.commit()
    db.refresh(ss)
    return ss


def delete(db: Session, ss: SavedSearch) -> None:
    scheduler_service.unschedule(db, KIND, ss.id)
    db.delete(ss)
    db.commit()


def to_dict(db: Session, ss: SavedSearch) -> dict[str, Any]:
    run = scheduler_service.get_run(db, KIND, ss.id)
    cadence = json.loads(run.cadence_json) if run and run.cadence_json else None
    return {
        "id": ss.id,
        "question": ss.question,
        "answer_language": ss.answer_language,
        "scope": _load_scope(ss),
        "cadence": cadence,
        "next_run_at": run.next_run_at if run and ss.enabled else None,
        "notify_email": ss.notify_email,
        "enabled": ss.enabled,
        "created_at": ss.created_at,
        "last_run_at": ss.last_run_at,
        "last_status": ss.last_status,
        "last_error": ss.last_error,
        "last_success_at": ss.last_success_at,
        "last_exchange_id": ss.last_exchange_id,
        "last_answer": _last_answer(db, ss),
    }


def _last_answer(db: Session, ss: SavedSearch) -> str | None:
    if not ss.last_exchange_id:
        return None
    row = db.query(LibraryQAExchange.answer).filter(LibraryQAExchange.id == ss.last_exchange_id).first()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Running


def scope_document_ids(db: Session, tenant_id: str, scope: dict | None) -> list[str]:
    """The documents a run may cite: the tenant's visible set, narrowed by
    the scope (``qa_scope_service``). An empty shelf, or a tenant with nothing
    ingested, yields ``[]``, which retrieves nothing; it never widens."""
    return qa_scope_service.resolve_document_ids(db, tenant_id, scope)


def reference_ids(references: list[dict]) -> list[str]:
    """The cited document set, as the stable citation key each reference carries."""
    out = {str(r.get("video_id")) for r in references if r.get("video_id")}
    return sorted(out)


def _record(db: Session, ss: SavedSearch, status: str, error: str | None = None) -> None:
    ss.last_run_at = _now()
    ss.last_status = status
    ss.last_error = error[:2000] if error else None
    db.commit()


def execute(db: Session, saved_search_id: str, *, trigger: str = "schedule", agent=None) -> dict[str, Any]:
    """Run a saved search once. ``trigger`` is ``schedule`` (the tick) or
    ``manual`` (Run now). Returns ``{status, exchange_id?}``; never raises,
    because the caller is a Celery task whose failure would only be logged.
    ``agent`` defaults to the library Q&A agent (tests pass a fake)."""
    ss = db.get(SavedSearch, saved_search_id)
    if ss is None:
        return {"status": STATUS_MISSING}
    if trigger == "schedule" and not ss.enabled:
        return {"status": STATUS_DISABLED}
    user = db.get(User, ss.tenant_id)
    if user is None:
        return {"status": STATUS_MISSING}

    if not tier_service.has_feature(user, FEATURE):
        _record(db, ss, STATUS_FEATURE, "This plan no longer includes saved searches.")
        return {"status": STATUS_FEATURE}

    from app.services import quota_metering_service

    allowed, _resets = quota_metering_service.check_quota(db, user, QUOTA_RESOURCE)
    if not allowed:
        # D-045: enforce before the run. Nothing is spent, the baseline stays.
        _record(db, ss, STATUS_QUOTA, "Monthly library question quota reached; this run was skipped.")
        return {"status": STATUS_QUOTA}

    scope = _load_scope(ss)
    try:
        document_ids = scope_document_ids(db, user.id, scope)
    except (qa_scope_service.ScopeNotFound, qa_scope_service.UnknownScopeKey):
        _record(db, ss, STATUS_SCOPE_MISSING, "The shelf this search was scoped to no longer exists.")
        return {"status": STATUS_SCOPE_MISSING}

    try:
        from app.services import chroma_service, corpus_stats_service, llm_service, subscription_service

        if agent is None:
            from app.agents.qa_agent import run_library_qa_agent as agent  # noqa: N813

        corpus_statistics = corpus_stats_service.corpus_statistics_for_document_ids(db, document_ids)
        channel_weights = subscription_service.channel_weights(db, user.id)
        with llm_service.byok_context(user.id, db):
            result = agent(
                question=ss.question,
                answer_language=ss.answer_language,
                visible_document_ids=document_ids,
                corpus_statistics=corpus_statistics,
                output_length=None,
                channel_weights=channel_weights,
            )
        answer = result.get("answer", "") or ""
        references = result.get("references", []) or []

        quota_metering_service.record_usage(db, user.id, QUOTA_RESOURCE)
        exchange = LibraryQAExchange(
            question=ss.question,
            answer=answer,
            references_json=json.dumps(references),
            answer_language=ss.answer_language,
            tenant_id=user.id,
            # S-8.1.4's shape: the narrowing scope plus where it came from.
            scope_json=qa_scope_service.dump({**(scope or {}), "saved_search_id": ss.id}),
        )
        db.add(exchange)
        db.flush()

        ss.last_success_at = _now()
        ss.last_exchange_id = exchange.id
        ss.last_answer_hash = hashlib.sha256(answer.encode("utf-8")).hexdigest()
        ss.last_reference_ids_json = json.dumps(reference_ids(references))
        _record(db, ss, STATUS_OK)
        db.refresh(exchange)
        try:
            chroma_service.upsert_qa_exchange(exchange, source="library")
        except Exception:  # pragma: no cover - indexing never fails a run
            logger.exception("saved search %s: Q&A index upsert failed", ss.id)
        return {"status": STATUS_OK, "exchange_id": exchange.id}
    except Exception as e:  # noqa: BLE001 - a run failure is recorded, not raised
        logger.exception("saved search %s: run failed", saved_search_id)
        db.rollback()
        ss = db.get(SavedSearch, saved_search_id)
        if ss is not None:
            _record(db, ss, STATUS_FAILED, f"{type(e).__name__}: {e}")
        return {"status": STATUS_FAILED}
