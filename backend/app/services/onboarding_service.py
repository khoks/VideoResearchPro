"""First-run onboarding state and activation events (S-8.10.1 / M10).

The wizard at ``/welcome`` (plan: docs/plans/m10-onboarding.md) keeps its
progress on the user row so it survives devices: ``users.onboarded_at`` and
``users.onboarding_state_json``. Milestones that other surfaces produce —
the first run, its completion, the first report opened — are DERIVED on
read from ``jobs`` and ``audit_log`` rather than flipped by the Celery task
that finishes the run, so the worker needs no onboarding code.

Activation events go to ``audit_log`` (best-effort, as every audit write):
``onboarding_started`` / ``_completed`` / ``_skipped`` from the wizard,
``first_job_created`` from job creation, ``first_report_opened`` from the
reader's body route, ``first_cited_answer`` from the job and library Q&A
routers.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.job import Job
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.models.qa_history_exchange import QAHistoryExchange
from app.models.user import User
from app.services import audit_service

logger = logging.getLogger(__name__)

STEPS = 3
MAX_CHANNELS = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def load_state(user: User) -> dict[str, Any] | None:
    """The stored state, or None when the wizard was never touched. A
    corrupt value reads as never started rather than failing the request."""
    if not user.onboarding_state_json:
        return None
    try:
        data = json.loads(user.onboarding_state_json)
        return data if isinstance(data, dict) else None
    except (TypeError, ValueError):
        logger.warning("onboarding_state_json for user %s is not JSON; treating as unset", user.id)
        return None


def _default_state() -> dict[str, Any]:
    return {
        "step": 1,
        "choices": {"channels": [], "first_job_id": None},
        "dismissed": False,
        "started_at": None,
        "completed_at": None,
        "dismissed_at": None,
        # S-8.10.2: the jobs page's first-run checklist, hidden on request.
        "checklist_dismissed": False,
        "checklist_dismissed_at": None,
    }


def _has_event(db: Session, user_id: str, event: audit_service.Event) -> bool:
    return (
        db.query(AuditLog.id)
        .filter(AuditLog.user_id == user_id, AuditLog.event == event.value)
        .first()
        is not None
    )


def milestones(db: Session, user: User, state: dict[str, Any] | None) -> dict[str, Any]:
    jobs = db.query(Job).filter(Job.tenant_id == user.id)
    count = jobs.count()
    first_id = (state or {}).get("choices", {}).get("first_job_id")
    first = None
    if first_id:
        first = jobs.filter(Job.id == first_id).first()
    if first is None:
        first = jobs.order_by(Job.created_at.asc()).first()
    return {
        "jobs": count,
        "first_job": (
            {
                "id": first.id,
                "job_type": first.job_type,
                "status": first.status,
                "has_report": first.report_path is not None,
            }
            if first
            else None
        ),
        "report_opened": _has_event(db, user.id, audit_service.Event.FIRST_REPORT_OPENED),
        "questions": _questions_asked(db, user.id),
    }


def _questions_asked(db: Session, user_id: str) -> int:
    """Questions the caller asked on any surface: a run, the library, or the
    Q&A history chat (S-8.10.2's third checklist item)."""
    return sum(
        db.query(model.id).filter(model.tenant_id == user_id).count()
        for model in (QAExchange, LibraryQAExchange, QAHistoryExchange)
    )


def should_onboard(user: User, state: dict[str, Any] | None, job_count: int) -> bool:
    """Send this account to /welcome from `/`?

    Yes while the wizard is unfinished and not skipped, and either the
    account has never started a run or the wizard is already under way (so
    a reload mid-wizard resumes it). Accounts that had runs before the
    wizard existed are left alone: the plan's open question 2 (show it to
    existing accounts once?) taken at its least intrusive answer.
    """
    if user.onboarded_at is not None:
        return False
    if state and state.get("dismissed"):
        return False
    if state and state.get("started_at"):
        return True
    return job_count == 0


def _channel_key(raw: str) -> str:
    """A channel as typed, folded so a handle or a channel id and its URL
    compare equal (``@Name``, ``youtube.com/@name/``,
    ``https://www.youtube.com/@name``; ``UC…``, ``youtube.com/channel/UC…``)."""
    key = raw.strip().lower()
    for prefix in ("https://", "http://"):
        if key.startswith(prefix):
            key = key[len(prefix):]
    for prefix in ("www.", "m."):
        if key.startswith(prefix):
            key = key[len(prefix):]
    if key.startswith("youtube.com/"):
        key = key[len("youtube.com/"):]
    if key.startswith("channel/"):
        key = key[len("channel/"):]
    key = key.split("?", 1)[0].rstrip("/")
    for suffix in ("/videos", "/featured", "/streams", "/shorts"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
    return key


def channels_not_yet_run(db: Session, user: User, state: dict[str, Any] | None) -> list[str]:
    """The wizard's channels that none of the caller's runs has named yet
    (T-8.10.1.7), in the order chosen. The first run reads one of them; the
    submit page pre-fills its channel list with the rest. A run counts
    whatever became of it: the reader has acted on that channel."""
    chosen = (state or {}).get("choices", {}).get("channels") or []
    if not chosen:
        return []
    named: set[str] = set()
    for (raw,) in db.query(Job.channel_list).filter(Job.tenant_id == user.id, Job.channel_list.isnot(None)):
        try:
            values = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(values, list):
            named.update(_channel_key(v) for v in values if isinstance(v, str))
    out: list[str] = []
    for c in chosen:
        if isinstance(c, str) and c.strip() and _channel_key(c) not in named and c not in out:
            out.append(c)
    return out


def payload(db: Session, user: User) -> dict[str, Any]:
    state = load_state(user)
    m = milestones(db, user, state)
    return {
        "onboarded_at": _iso(user.onboarded_at),
        "state": {**_default_state(), **(state or {})},
        "started": state is not None and bool(state.get("started_at")),
        "milestones": m,
        "should_onboard": should_onboard(user, state, m["jobs"]),
        "channels_not_yet_run": channels_not_yet_run(db, user, state),
    }


class OnboardingError(ValueError):
    """A patch that names something the caller does not own."""


def update(
    db: Session,
    user: User,
    *,
    step: int | None = None,
    channels: list[str] | None = None,
    first_job_id: str | None = None,
    completed: bool = False,
    dismissed: bool = False,
    checklist_dismissed: bool = False,
    request=None,
) -> dict[str, Any]:
    """Merge a patch into the user's state; returns the fresh payload."""
    previous = load_state(user)
    state = {**_default_state(), **(previous or {})}
    events: list[audit_service.Event] = []
    touches_wizard = any(
        v for v in (step is not None, channels is not None, first_job_id is not None, completed, dismissed)
    )
    # Hiding the jobs-page checklist is not starting the wizard.
    if touches_wizard and not state.get("started_at"):
        state["started_at"] = _now().isoformat()
        events.append(audit_service.Event.ONBOARDING_STARTED)

    if step is not None:
        state["step"] = max(1, min(STEPS, step))
    if channels is not None:
        cleaned = []
        for c in channels:
            c = c.strip()
            if c and c not in cleaned:
                cleaned.append(c[:300])
        state.setdefault("choices", {})["channels"] = cleaned[:MAX_CHANNELS]
    if first_job_id is not None:
        owned = db.query(Job.id).filter(Job.id == first_job_id, Job.tenant_id == user.id).first()
        if owned is None:
            raise OnboardingError("first_job_id is not one of your runs")
        state.setdefault("choices", {})["first_job_id"] = first_job_id
    if completed and user.onboarded_at is None:
        user.onboarded_at = _now()
        state["completed_at"] = user.onboarded_at.isoformat()
        events.append(audit_service.Event.ONBOARDING_COMPLETED)
    if dismissed and not state.get("dismissed"):
        state["dismissed"] = True
        state["dismissed_at"] = _now().isoformat()
        events.append(audit_service.Event.ONBOARDING_SKIPPED)
    if checklist_dismissed and not state.get("checklist_dismissed"):
        state["checklist_dismissed"] = True
        state["checklist_dismissed_at"] = _now().isoformat()

    user.onboarding_state_json = json.dumps(state)
    db.add(user)
    db.commit()
    db.refresh(user)
    for event in events:
        audit_service.record(
            db,
            event=event,
            user_id=user.id,
            request=request,
            metadata={"step": state.get("step")},
        )
    return payload(db, user)


def note_job_created(db: Session, user: User, job: Job) -> None:
    """`first_job_created`, once per account. Never fails the caller."""
    try:
        if db.query(Job.id).filter(Job.tenant_id == user.id).count() != 1:
            return
        if _has_event(db, user.id, audit_service.Event.FIRST_JOB_CREATED):
            return
        audit_service.record(
            db,
            event=audit_service.Event.FIRST_JOB_CREATED,
            user_id=user.id,
            metadata={"job_id": job.id, "job_type": job.job_type},
        )
    except Exception:  # pragma: no cover - auditing is best-effort
        logger.exception("onboarding: first_job_created not recorded")


def _cites_a_source(ref: Any) -> bool:
    """A citation of a source in the library. A note (S-8.5.2) is the
    reader's own words, so an answer citing only notes does not count."""
    return isinstance(ref, dict) and ref.get("source_type") != "note"


def note_cited_answer(
    db: Session,
    user: User,
    *,
    surface: str,
    exchange_id: str,
    references: list[Any] | None,
    job_id: str | None = None,
) -> bool:
    """`first_cited_answer`, once per account (T-8.10.1.6): the first stored
    answer, on a run or in the library, that cites at least one source.
    Returns whether it was written. Never fails the caller."""
    try:
        cited = sum(1 for r in references or [] if _cites_a_source(r))
        if cited == 0:
            return False
        if _has_event(db, user.id, audit_service.Event.FIRST_CITED_ANSWER):
            return False
        metadata: dict[str, Any] = {"surface": surface, "exchange_id": exchange_id, "citations": cited}
        if job_id:
            metadata["job_id"] = job_id
        row = audit_service.record(
            db,
            event=audit_service.Event.FIRST_CITED_ANSWER,
            user_id=user.id,
            metadata=metadata,
        )
        return row is not None
    except Exception:  # pragma: no cover - auditing is best-effort
        logger.exception("onboarding: first_cited_answer not recorded")
        return False


def note_report_opened(db: Session, user: User, job: Job) -> None:
    """`first_report_opened`, once per account — the M10 activation
    milestone. Recorded when the reader fetches a report body."""
    try:
        if _has_event(db, user.id, audit_service.Event.FIRST_REPORT_OPENED):
            return
        audit_service.record(
            db,
            event=audit_service.Event.FIRST_REPORT_OPENED,
            user_id=user.id,
            metadata={"job_id": job.id},
        )
    except Exception:  # pragma: no cover - auditing is best-effort
        logger.exception("onboarding: first_report_opened not recorded")
