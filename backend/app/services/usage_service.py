"""Per-tenant usage metering: LLM tokens by feature, YouTube Data API units,
Whisper audio seconds (E-5.2).

Records, never limits. D-111 took the daily-token line off the pricing page
because nothing enforced it; this module makes the numbers real without
adding a limit. ``GET /api/v1/usage`` reads them back for the signed-in user.

**How a call gets counted.** A *metering scope* names the tenant the work is
for. Open one at the entry point of user-triggered work::

    with usage_service.metered(db, current_user.id):
        run_some_agent(...)

``llm_service.byok_context`` opens one too, so every path that is already
BYOK-correct (D-041) is metered without a second line. Inside a scope:

- ``llm_service.get_llm_for`` attaches a LangChain callback to the client it
  builds. Every call that client makes adds its reported input and output
  tokens, plus one call, to the scope. The feature is the scope's own when
  the entry point named one (library Q&A shares the job-Q&A sub-query and
  reference use cases, so it names ``library_qa``), otherwise the use case's
  entry in ``USE_CASE_FEATURES``.
- ``quota_service.record`` (every YouTube Data API request) adds its units,
  under the kind of call: ``youtube_search``, ``video_metadata`` or
  ``channel_sync``.
  The install-wide ``api_quota_log`` row is written exactly as before.
- ``youtube_service._whisper_transcribe_with_retry``, which every hosted
  Whisper call goes through (the YouTube fallback, podcast audio, Echo
  recordings), adds the seconds each response reports as ``whisper_seconds``:
  what OpenAI bills, chunk overlap included. It is charged to the scope's
  feature, else ``ingest``; an Echo recording's scope names ``echo_shares``.

Nested scopes for the same tenant share the outermost one's ledger, and the
outermost scope that named a feature wins (a saved search's run is a
``saved_search``, though it asks through the library-Q&A core).

**When it is written.** The outermost scope writes its ledger when it closes:
one upsert per (day, feature, metric) into ``usage_records`` plus the
matching daily ``quota_usage`` totals (``llm_tokens_in`` / ``llm_tokens_out``
/ ``youtube_units``) that ``/auth/quota`` already reports. It writes through
**its own session** on the caller's engine and commits that, never the
caller's: the meter neither commits nor rolls back the caller's work, pending
or flushed. When the caller's open transaction has already written to the
database (an ORM flush, a DML statement, or, on SQLite, any open write
transaction on its connection), a second connection would wait on the
caller's write lock (SQLite) or row locks (Postgres), so the write waits
until the caller's outermost transaction ends, by commit, rollback or close.
Tokens spent on work that is then rolled back are still recorded: they were
spent. Metering never raises into the work it measures.

**Part-way through long work.** A worker that dies never reaches the close,
so an open scope also writes what it has counted so far, at most once every
``USAGE_FLUSH_INTERVAL_SECONDS`` (``checkpoint``). It tries after every model
call and every Whisper response (the chunks of a split recording are billed
minutes apart inside one iteration of the caller's loop), and wherever a long
loop calls ``checkpoint()``, which is how YouTube units get written in a run
with no model calls, and what a try was too early for or had to leave. It
keeps the rules above: its own session, and while the caller's transaction has
written it leaves the amounts where they are for a later checkpoint or the
close. Each amount leaves the ledger before it is written and goes back only
when that write rolled back, so a checkpoint and the close never write the
same amount. A redelivered task starts with an empty ledger and adds only what
it spends itself; work it repeats it really did pay for twice. A dead worker
loses what it counted since its last write, never more.

What is not counted: local models that report no usage (their calls are
counted, their tokens are not), a Whisper request that got no response (OpenAI
may still bill one that timed out), embeddings (local), and the startup probes
and "Verify key" checks (``probe_config`` builds its own clients).
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

METRICS: tuple[str, ...] = ("llm_tokens_in", "llm_tokens_out", "llm_calls", "youtube_units", "whisper_seconds")

# The daily totals mirrored into quota_usage (the keys /auth/quota reports).
_QUOTA_METRICS: tuple[str, ...] = ("llm_tokens_in", "llm_tokens_out", "youtube_units")

# Feature key -> label shown on the subscription page. Order is display order
# for features with equal usage.
FEATURES: dict[str, str] = {
    "job_qa": "Job Q&A",
    "library_qa": "Library Q&A",
    "qa_history": "Q&A history chat",
    "report": "Reports",
    "search": "Topic search",
    "knowledge": "Knowledge reports",
    "ingest": "Reading sources",
    "visual": "Frame capture",
    "suggestions": "Question suggestions",
    "saved_search": "Saved searches",
    "echo_draft": "Speak as me",
    "echo_signals": "Echo learning your voice",
    "echo_shares": "Echo shares",
    "author": "Author Studio",
    "youtube_search": "Searches (YouTube)",
    "video_metadata": "Video details (YouTube)",
    "channel_sync": "Channel listings (YouTube)",
    "other": "Other",
}

# Every registered LLM use case -> the feature it is charged to when the
# scope names none. ``tests/test_services/test_usage_service.py`` checks this
# covers the whole registry, so a new use case cannot ship unmetered.
USE_CASE_FEATURES: dict[str, str] = {
    "qa_clarification": "job_qa",
    "qa_sub_query_expansion": "job_qa",
    "qa_refine_context": "job_qa",
    "qa_formulate_answer": "job_qa",
    "qa_extract_references": "job_qa",
    "library_qa_clarification": "library_qa",
    "library_qa_refine_context": "library_qa",
    "library_qa_formulate_answer": "library_qa",
    "qa_history_refine_context": "qa_history",
    "qa_history_formulate_answer": "qa_history",
    "knowledge_extract_batch": "knowledge",
    "knowledge_synthesize_report": "knowledge",
    "search_plan_queries": "search",
    "search_rank_and_curate": "search",
    "social_classify_stance": "ingest",
    "report_map_chunks": "report",
    "report_reduce_summaries": "report",
    "report_compose": "report",
    "report_channel": "report",
    "report_compose_channel_section": "report",
    "visual_select_moments": "visual",
    "visual_describe_frame": "visual",
    "temporal_scope_extract": "ingest",
    "code_mixing_detect": "ingest",
    "code_mixing_render_english": "ingest",
    "qa_suggest_questions": "suggestions",
    "author_book_outline": "author",
    "author_book_prose": "author",
    "author_deck_outline": "author",
    "author_newsletter_compose": "author",
    "saved_search_judge": "saved_search",
    "echo_classify_intent": "echo_draft",
    "echo_draft": "echo_draft",
    "echo_critique": "echo_draft",
    "echo_extract_signals": "echo_signals",
    "echo_share_ocr": "echo_shares",
}

# YouTube Data API operation (``quota_service.OPERATION_COSTS``) -> feature:
# the kind of call, not the action that made it. ``search.list`` is not only
# topic search: resolving a channel typed by name falls back to it (100
# units) in channel jobs and subscription syncs, so its units are
# ``youtube_search``, never the ``search`` feature (topic search's LLM calls).
YOUTUBE_FEATURES: dict[str, str] = {
    "search": "youtube_search",
    "videos": "video_metadata",
    "channels": "channel_sync",
    "playlistItems": "channel_sync",
}


def feature_for_use_case(use_case: str) -> str:
    return USE_CASE_FEATURES.get(use_case, "other")


def label_for(feature: str) -> str:
    return FEATURES.get(feature, feature.replace("_", " ").capitalize())


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _clock() -> float:
    return time.monotonic()


# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------


class _Ledger:
    """Amounts waiting to be written, keyed ``(day, feature, metric)``.

    Thread-safe: report map batches run on a pool and their callbacks land
    here concurrently."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._amounts: dict[tuple[date, str, str], int] = {}
        self._last_flush = _clock()

    def add(self, feature: str, metric: str, amount: int) -> None:
        if amount <= 0:
            return
        key = (_today(), feature, metric)
        with self._lock:
            self._amounts[key] = self._amounts.get(key, 0) + int(amount)

    def drain(self) -> dict[tuple[date, str, str], int]:
        with self._lock:
            out, self._amounts = self._amounts, {}
        return out

    def snapshot(self) -> dict[tuple[date, str, str], int]:
        with self._lock:
            return dict(self._amounts)

    def restore(self, entries: dict[tuple[date, str, str], int]) -> None:
        """Take back amounts a write rolled back; they keep the day they were spent."""
        with self._lock:
            for key, amount in entries.items():
                self._amounts[key] = self._amounts.get(key, 0) + amount

    def flush_due(self, interval: float) -> bool:
        return _clock() - self._last_flush >= interval

    def claim_flush(self, interval: float) -> bool:
        """True for the one caller that may flush now: pool threads race here
        and one of them wins. The interval restarts only for a write, so a try
        that had to wait does not cost the next one its turn."""
        now = _clock()
        with self._lock:
            if now - self._last_flush < interval:
                return False
            self._last_flush = now
            return True


@dataclass
class Scope:
    tenant_id: str
    feature: str | None
    ledger: _Ledger = field(default_factory=_Ledger)
    # The session the outermost scope closes on and the thread that owns it:
    # a checkpoint on any other thread must not touch that session.
    db: Session | None = None
    thread: int = field(default_factory=threading.get_ident)

    def add_llm(self, use_case: str, tokens_in: int | None, tokens_out: int | None) -> None:
        feature = self.feature or feature_for_use_case(use_case)
        self.ledger.add(feature, "llm_calls", 1)
        self.ledger.add(feature, "llm_tokens_in", tokens_in or 0)
        self.ledger.add(feature, "llm_tokens_out", tokens_out or 0)

    def add_youtube(self, operation: str, units: int) -> None:
        self.ledger.add(YOUTUBE_FEATURES.get(operation, "other"), "youtube_units", units)

    def add_whisper(self, seconds: float) -> None:
        # OpenAI bills to the nearest second, and a clip under half a second
        # was still sent, so a billed call never rounds away to nothing.
        if seconds > 0:
            self.ledger.add(self.feature or "ingest", "whisper_seconds", max(1, round(seconds)))


_current: ContextVar[Scope | None] = ContextVar("usage_scope", default=None)


def current_scope() -> Scope | None:
    return _current.get()


@contextmanager
def metered(db: Session | None, tenant_id: str | None, *, feature: str | None = None) -> Iterator[Scope | None]:
    """Meter everything inside the block against ``tenant_id``.

    No tenant or no session: a no-op (system work, startup, scripts). A scope
    already open for the same tenant is joined, not replaced: its ledger, and
    its feature if it named one. A different tenant opens its own."""
    if not tenant_id or db is None:
        yield None
        return
    parent = _current.get()
    if parent is not None and parent.tenant_id == tenant_id:
        child = Scope(
            tenant_id=tenant_id, feature=parent.feature or feature, ledger=parent.ledger,
            db=parent.db, thread=parent.thread,
        )
        token = _current.set(child)
        try:
            yield child
        finally:
            _current.reset(token)
        return

    scope = Scope(tenant_id=tenant_id, feature=feature, db=db)
    token = _current.set(scope)
    try:
        yield scope
    finally:
        _current.reset(token)
        flush(db, scope)


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def tokens_from_result(result: Any) -> tuple[int | None, int | None]:
    """(input, output) tokens from a LangChain ``LLMResult``.

    Prefers each generation's ``message.usage_metadata`` (the normalised
    field every provider integration fills), falling back to the provider-raw
    ``llm_output`` (``token_usage`` on OpenAI, ``usage`` on Anthropic). None
    when nothing reported usage (most local servers)."""
    tin = tout = 0
    found = False
    for gens in getattr(result, "generations", None) or []:
        for gen in gens or []:
            usage = getattr(getattr(gen, "message", None), "usage_metadata", None)
            if isinstance(usage, dict) and (
                isinstance(usage.get("input_tokens"), int) or isinstance(usage.get("output_tokens"), int)
            ):
                tin += int(usage.get("input_tokens") or 0)
                tout += int(usage.get("output_tokens") or 0)
                found = True
    if found:
        return tin, tout
    raw = getattr(result, "llm_output", None)
    if isinstance(raw, dict):
        for key, (a, b) in (("token_usage", ("prompt_tokens", "completion_tokens")), ("usage", ("input_tokens", "output_tokens"))):
            u = raw.get(key)
            if isinstance(u, dict) and (isinstance(u.get(a), int) or isinstance(u.get(b), int)):
                return int(u.get(a) or 0), int(u.get(b) or 0)
    return None, None


try:  # pragma: no branch - langchain-core is a hard dependency
    from langchain_core.callbacks import BaseCallbackHandler
except Exception:  # pragma: no cover
    BaseCallbackHandler = object  # type: ignore[assignment,misc]


class UsageCallback(BaseCallbackHandler):  # type: ignore[misc,valid-type]
    """Adds one model call's usage to the scope it was built in."""

    raise_error = False
    run_inline = True

    def __init__(self, scope: Scope, use_case: str) -> None:
        super().__init__()
        self.scope = scope
        self.use_case = use_case

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        try:
            tin, tout = tokens_from_result(response)
            self.scope.add_llm(self.use_case, tin, tout)
            _checkpoint(self.scope)
        except Exception:  # noqa: BLE001 - metering never breaks a call
            logger.exception("usage: could not count a %s call", self.use_case)


def attach(llm: Any, use_case: str, *, tenant_id: str | None = None) -> Any:
    """Called by ``llm_service.get_llm_for`` on every client it builds: when a
    scope is open, the client's calls are counted against it."""
    scope = _current.get()
    if scope is None:
        if tenant_id:
            logger.debug("usage: %s built for tenant %s outside a metering scope", use_case, tenant_id[:8])
        return llm
    try:
        handler = UsageCallback(scope, use_case)
        existing = getattr(llm, "callbacks", None)
        if existing is None:
            llm.callbacks = [handler]
        elif isinstance(existing, list):
            llm.callbacks = [*existing, handler]
        elif hasattr(existing, "add_handler"):
            existing.add_handler(handler, inherit=True)
        else:
            llm.callbacks = [handler]
    except Exception:  # noqa: BLE001
        logger.exception("usage: could not attach the meter to a %s client", use_case)
    return llm


def record_youtube(operation: str, units: int) -> None:
    """Called by ``quota_service.record`` for every YouTube Data API request."""
    scope = _current.get()
    if scope is None:
        return
    try:
        scope.add_youtube(operation, units)
    except Exception:  # noqa: BLE001
        logger.exception("usage: could not count a YouTube %s call", operation)


def record_whisper(seconds: float) -> None:
    """Called for every response from the hosted Whisper API, with the audio
    seconds it reports. No scope, nothing recorded."""
    scope = _current.get()
    if scope is None:
        return
    try:
        scope.add_whisper(seconds)
        _checkpoint(scope)
    except Exception:  # noqa: BLE001
        logger.exception("usage: could not count Whisper audio")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _upsert(db: Session, model: Any, values: dict, conflict: list[str], counter: str, now: datetime) -> None:
    """``INSERT ... ON CONFLICT DO UPDATE counter = counter + excluded``: one
    statement, so two workers closing scopes at once never collide."""
    dialect = db.get_bind().dialect.name
    if dialect in ("sqlite", "postgresql"):
        if dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        stmt = insert(model).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict,
            set_={counter: getattr(model, counter) + getattr(stmt.excluded, counter), "updated_at": now},
        )
        db.execute(stmt)
        return
    row = db.query(model).filter_by(**{k: values[k] for k in conflict}).first()  # pragma: no cover
    if row is None:  # pragma: no cover
        db.add(model(**values))
    else:  # pragma: no cover
        setattr(row, counter, (getattr(row, counter) or 0) + values[counter])
        row.updated_at = now


def _write(db: Session, tenant_id: str, entries: dict[tuple[date, str, str], int]) -> None:
    from app.models.quota_usage import QuotaUsage
    from app.models.usage_record import UsageRecord

    now = datetime.now(timezone.utc)
    quota: dict[tuple[date, str], int] = {}
    with db.no_autoflush:
        for (day, feature, metric), amount in sorted(entries.items()):
            _upsert(
                db, UsageRecord,
                {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "day": day, "feature": feature,
                 "metric": metric, "amount": amount, "updated_at": now},
                ["tenant_id", "day", "feature", "metric"], "amount", now,
            )
            if metric in _QUOTA_METRICS:
                quota[(day, metric)] = quota.get((day, metric), 0) + amount
        for (day, metric), amount in sorted(quota.items()):
            _upsert(
                db, QuotaUsage,
                {"id": str(uuid.uuid4()), "user_id": tenant_id, "resource": metric, "period_kind": "daily",
                 "period_start": datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
                 "consumed": amount, "updated_at": now},
                ["user_id", "resource", "period_kind", "period_start"], "consumed", now,
            )


# ``Session.info`` keys. ``_WROTE``: the caller's current transaction has sent
# a write to the database. ``_DEFERRED``: ledgers waiting for that transaction
# to end. Both are dropped when the outermost transaction ends.
_WROTE = "usage_tx_wrote"
_DEFERRED = "usage_deferred_writes"
_TEXT_DML = ("INSERT", "UPDATE", "DELETE", "REPLACE", "UPSERT", "MERGE")


@event.listens_for(Session, "after_flush")
def _note_flush(session: Session, flush_context: Any) -> None:
    session.info[_WROTE] = True


@event.listens_for(Session, "do_orm_execute")
def _note_dml(state: Any) -> None:
    """``session.execute(insert/update/delete)`` and ``Query.update/delete``
    write without a flush; so does a ``text()`` DML statement."""
    try:
        if state.is_insert or state.is_update or state.is_delete:
            state.session.info[_WROTE] = True
            return
        text = getattr(state.statement, "text", None)
        if isinstance(text, str) and text.lstrip().upper().startswith(_TEXT_DML):
            state.session.info[_WROTE] = True
    except Exception:  # noqa: BLE001 - bookkeeping never breaks a statement
        pass


@event.listens_for(Session, "after_transaction_end")
def _on_transaction_end(session: Session, transaction: Any) -> None:
    """The caller's outermost transaction is over (committed, rolled back or
    closed), its connection released: write what waited for it."""
    if transaction.parent is not None:  # a SAVEPOINT; the outer one still runs
        return
    session.info.pop(_WROTE, None)
    waiting = session.info.pop(_DEFERRED, None)
    for bind, tenant_id, entries in waiting or ():
        _write_own(bind, tenant_id, entries)


def _caller_has_written(db: Session) -> bool:
    """Whether the caller's open transaction has already written to the
    database. Unflushed changes do not count: they are not in the database
    yet, and the meter's own session cannot touch them.

    On SQLite the DBAPI connection's ``in_transaction`` is exact (pysqlite
    opens a transaction only for a write), and it also sees writes the
    session events cannot: ``bulk_save_objects`` and statements run on
    ``db.connection()`` directly. Elsewhere the events decide."""
    try:
        if not db.is_active:  # a failed flush; the caller must roll back
            return True
        if db.info.get(_WROTE):
            return True
        if not db.in_transaction():
            return False
        conn = db.connection()
        if conn.dialect.name == "sqlite":
            return bool(getattr(conn.connection.dbapi_connection, "in_transaction", False))
        return False
    except Exception:  # noqa: BLE001 - unsure: wait for the transaction to end
        return True


def _write_own(bind: Any, tenant_id: str, entries: dict[tuple[date, str, str], int]) -> bool:
    """Write and commit a ledger in a session of the meter's own. False when
    the write failed and was rolled back, so nothing of it was kept."""
    own = Session(bind=bind, autoflush=False, expire_on_commit=False)
    try:
        _write(own, tenant_id, entries)
        own.commit()
        return True
    except Exception:  # noqa: BLE001
        logger.exception("usage: write failed for tenant %s", tenant_id[:8])
        try:
            own.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False
    finally:
        own.close()


def flush(db: Session, scope: Scope) -> None:
    """Write the scope's ledger (see the module docstring for when)."""
    entries = scope.ledger.drain()
    if not entries:
        return
    tenant_id = scope.tenant_id
    try:
        bind = db.get_bind()
        if _caller_has_written(db):
            db.info.setdefault(_DEFERRED, []).append((bind, tenant_id, entries))
            return
    except Exception:  # noqa: BLE001
        logger.exception("usage: could not write for tenant %s", tenant_id[:8])
        return
    _write_own(bind, tenant_id, entries)


def _checkpoint(scope: Scope | None) -> bool:
    interval = settings.USAGE_FLUSH_INTERVAL_SECONDS
    if scope is None or interval <= 0 or not scope.ledger.flush_due(interval):
        return False
    try:
        db = scope.db
        # A Session is not thread-safe, and report map batches run on a pool
        # while the task's own thread waits for them, so off that thread the
        # meter reads only the bookkeeping it keeps itself.
        if threading.get_ident() == scope.thread:
            wait = _caller_has_written(db)
        else:
            wait = bool(db.info.get(_WROTE))
        if wait:  # the amounts stay in the ledger for a later try or the close
            return False
        bind = db.get_bind()
    except Exception:  # noqa: BLE001
        logger.exception("usage: part-way write skipped for tenant %s", scope.tenant_id[:8])
        return False
    if not scope.ledger.claim_flush(interval):
        return False
    entries = scope.ledger.drain()
    if not entries:
        return False
    if _write_own(bind, scope.tenant_id, entries):
        return True
    scope.ledger.restore(entries)
    return False


def checkpoint() -> bool:
    """Write what the open scope has counted so far, if the interval has passed
    (see the module docstring). True when it wrote.

    For long loops, at a point where the caller has committed: a no-op without
    a scope, cheap before the interval, safe on any thread, and it never raises."""
    return _checkpoint(_current.get())


def record(db: Session, tenant_id: str, feature: str, metric: str, amount: int) -> None:
    """Write one amount now (outside any scope). Commits; never raises."""
    if amount <= 0 or not tenant_id:
        return
    if metric not in METRICS:
        raise ValueError(f"Unknown usage metric {metric!r}")
    scope = Scope(tenant_id=tenant_id, feature=feature)
    scope.ledger.add(feature, metric, amount)
    flush(db, scope)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _zero() -> dict[str, int]:
    return {m: 0 for m in METRICS}


def summary(db: Session, tenant_id: str, *, today: date | None = None, days: int = 30) -> dict[str, Any]:
    """The caller's usage today and over the last ``days`` days (today
    included), by feature. Only this tenant's rows are read."""
    from sqlalchemy import func

    from app.models.usage_record import UsageRecord

    today = today or _today()
    start = today - timedelta(days=days - 1)
    rows = (
        db.query(UsageRecord.day, UsageRecord.feature, UsageRecord.metric, UsageRecord.amount)
        .filter(UsageRecord.tenant_id == tenant_id, UsageRecord.day >= start, UsageRecord.day <= today)
        .all()
    )
    by_feature: dict[str, dict[str, dict[str, int]]] = {}
    totals = {"today": _zero(), "last_30_days": _zero()}
    for day, feature, metric, amount in rows:
        if metric not in METRICS:
            continue
        slot = by_feature.setdefault(feature, {"today": _zero(), "last_30_days": _zero()})
        slot["last_30_days"][metric] += int(amount or 0)
        totals["last_30_days"][metric] += int(amount or 0)
        if day == today:
            slot["today"][metric] += int(amount or 0)
            totals["today"][metric] += int(amount or 0)

    order = list(FEATURES)

    def _rank(item: tuple[str, dict]) -> tuple:
        feature, slot = item
        w = slot["last_30_days"]
        spent = w["llm_tokens_in"] + w["llm_tokens_out"]
        pos = order.index(feature) if feature in order else len(order)
        return (-spent, -w["youtube_units"], -w["whisper_seconds"], -w["llm_calls"], pos, feature)

    since = db.query(func.min(UsageRecord.day)).filter(UsageRecord.tenant_id == tenant_id).scalar()
    return {
        "today": today,
        "window_start": start,
        "window_days": days,
        "metered_since": since,
        "features": [
            {"feature": f, "label": label_for(f), "today": slot["today"], "last_30_days": slot["last_30_days"]}
            for f, slot in sorted(by_feature.items(), key=_rank)
        ],
        "totals": totals,
    }
