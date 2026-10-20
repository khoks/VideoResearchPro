"""Author Studio output service — I-6 foundation.

Three layers:

1. **CRUD** on Output rows (``create``, ``get``, ``list``, ``delete``).
2. **Outputter Protocol** + registry — concrete outputters implement
   ``generate(db, user, output) -> None`` which transitions
   ``output.status`` from ``generating`` → ``completed`` (writing
   ``content_text`` or ``content_path``) or ``failed`` (writing
   ``error_message``).
3. **Status state machine** — `pending` → `generating` → `completed`
   | `failed`, and `cancelled` from either live state. The service exposes
   transition helpers so concrete outputters don't manage status directly.

S-6.7.1 moved generation into the Celery worker (`tasks/output_tasks.py`):
`POST /author/outputs` writes a `pending` row and dispatches
`generate_output` on the owner's tier queue. Every status change and every
``report_progress`` call is published on `job_progress:{output_id}`, the
channel job progress already uses, so the WebSocket manager and the
frontend's `wsClient` needed no new channel. Cancellation is cooperative:
`cancel_output` marks the row and revokes the task, and the next
``report_progress`` an outputter makes raises ``OutputCancelled`` (a solo-pool
Windows worker cannot be interrupted mid-task, so revoke alone is not
enough).

v1 ships with one concrete outputter — `BookMarkdownOutputter` —
which performs deterministic structural concatenation of selected
job reports into a Markdown manuscript. No LLM is involved in the
v1 outputter; LLM-driven cohesion (chapter ordering, transition prose,
introductions) is a planned follow-up. The point of the v1 outputter
is to validate the schema + lifecycle + REST surface end-to-end with
real content the user can download.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Protocol

from sqlalchemy.orm import Session

from app.models.output import Output
from app.models.user import User

logger = logging.getLogger(__name__)


class OutputKind(str, Enum):
    BOOK = "book"
    SITE = "site"
    DECK = "deck"
    NEWSLETTER = "newsletter"
    REEL = "reel"


SUPPORTED_KINDS: frozenset[str] = frozenset(k.value for k in OutputKind)


class OutputStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # S-6.4.1: generation found nothing to make (a newsletter with nothing
    # new since the last issue). Not a failure; the reason is the row's
    # progress message.
    SKIPPED = "skipped"


TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        OutputStatus.COMPLETED.value,
        OutputStatus.FAILED.value,
        OutputStatus.CANCELLED.value,
        OutputStatus.SKIPPED.value,
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OutputError(RuntimeError):
    pass


class UnsupportedKindError(OutputError):
    pass


class NoOutputterError(OutputError):
    pass


class OutputCancelled(OutputError):
    """Raised by ``report_progress`` when the row was cancelled meanwhile."""


class OutputSkipped(OutputError):
    """Raised by an outputter that found nothing to make (S-6.4.1). The row
    ends ``skipped`` with this message as its progress message, and no
    content or files."""


class OutputUnavailable(OutputError):
    """A requested format needs a converter this server does not have
    (S-6.1.5: a book's PDF). The router answers 501 with the message, which
    says what to install; in the worker it fails the row like any error."""


# ---------------------------------------------------------------------------
# Outputter Protocol + registry
# ---------------------------------------------------------------------------


class Outputter(Protocol):
    """Interface every concrete output generator implements.

    Generation happens synchronously (for v1's simple outputters) but
    the Protocol doesn't preclude long-running async generation later
    — the lifecycle (pending → generating → completed | failed) is
    independent of how the generator implements ``generate``.
    """

    kind: str  # one of OutputKind values

    def generate(
        self, db: Session, user: User, output: Output
    ) -> None:
        """Read ``output.source_ids_json`` + ``output.parameters_json``,
        produce content, write to ``output.content_text`` or
        ``output.content_path``, and let the caller transition status.
        Raise ``OutputError`` on failure; the caller catches and
        transitions to ``failed`` with the error message.
        """


_OUTPUTTERS: dict[str, Outputter] = {}


def register_outputter(outputter: Outputter) -> None:
    """Register an outputter for ``outputter.kind``. Idempotent."""
    _OUTPUTTERS[outputter.kind] = outputter


def get_outputter(kind: str) -> Outputter | None:
    return _OUTPUTTERS.get(kind)


def list_outputters() -> list[str]:
    return sorted(_OUTPUTTERS.keys())


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_output(
    db: Session,
    *,
    user_id: str,
    kind: str,
    title: str,
    source_ids: Iterable[str] | None = None,
    parameters: dict[str, Any] | None = None,
) -> Output:
    if kind not in SUPPORTED_KINDS:
        raise UnsupportedKindError(
            f"Unknown output kind '{kind}'. Supported: {sorted(SUPPORTED_KINDS)}"
        )
    if not title or not title.strip():
        raise OutputError("title is required")

    row = Output(
        user_id=user_id,
        kind=kind,
        title=title.strip(),
        status=OutputStatus.PENDING.value,
        source_ids_json=json.dumps(list(source_ids or [])),
        parameters_json=json.dumps(parameters or {}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_output(db: Session, user_id: str, output_id: str) -> Output | None:
    """Cross-user isolation: only returns the row when it belongs to
    ``user_id``. 404-not-403 posture (caller decides response shape)."""
    return (
        db.query(Output)
        .filter(Output.id == output_id, Output.user_id == user_id)
        .first()
    )


def list_outputs(
    db: Session,
    user_id: str,
    *,
    kind: str | None = None,
    status: str | None = None,
) -> list[Output]:
    q = db.query(Output).filter(Output.user_id == user_id)
    if kind is not None:
        if kind not in SUPPORTED_KINDS:
            raise UnsupportedKindError(
                f"Unknown output kind '{kind}'. Supported: {sorted(SUPPORTED_KINDS)}"
            )
        q = q.filter(Output.kind == kind)
    if status is not None:
        q = q.filter(Output.status == status)
    return q.order_by(Output.created_at.desc()).all()


def delete_output(db: Session, user_id: str, output_id: str) -> bool:
    row = get_output(db, user_id, output_id)
    if row is None:
        return False
    # S-6.7.3: its citations (SQLite here does not enforce the FK cascade).
    from app.services import output_citation_service

    output_citation_service.delete_citations(db, row.id)
    # S-6.7.2: the row's artifact directory goes with it. Best effort: a file
    # that cannot be removed is left for scripts/sweep_output_artifacts.py.
    try:
        from app.services import output_artifacts

        output_artifacts.delete_artifacts(row)
    except Exception:  # noqa: BLE001
        logger.warning("output_service: could not remove artifacts for %s", output_id)
    db.delete(row)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def _publish_status(output_id: str, old: str, new: str, message: str) -> None:
    """Best-effort: progress is a convenience, never a reason to fail."""
    try:
        from app.services import progress_service

        progress_service.publish_status_change(output_id, old, new, message)
    except Exception:  # noqa: BLE001
        logger.warning("output_service: could not publish status for %s", output_id)


def _publish_progress(output: Output) -> None:
    try:
        from app.services import progress_service

        progress_service.publish_progress(
            output.id, output.status, output.progress_pct, output.progress_message or ""
        )
    except Exception:  # noqa: BLE001
        logger.warning("output_service: could not publish progress for %s", output.id)


def transition_to(
    db: Session,
    output: Output,
    new_status: OutputStatus | str,
    *,
    error_message: str | None = None,
    progress_message: str | None = None,
) -> None:
    """Update ``output.status`` (and optionally ``error_message`` /
    ``progress_message``), commit, and publish the change on
    `job_progress:{output_id}`. The state machine isn't strictly enforced
    (any → any) so callers can re-try generation."""
    old = output.status
    output.status = new_status.value if isinstance(new_status, OutputStatus) else new_status
    if error_message is not None:
        output.error_message = error_message
    if progress_message is not None:
        output.progress_message = progress_message[:500]
    output.updated_at = datetime.now(timezone.utc)
    db.commit()
    _publish_status(output.id, old, output.status, output.progress_message or output.status)


def _discard_artifacts(output: Output) -> None:
    """A run that did not complete leaves no files behind (S-6.7.2)."""
    try:
        from app.services import output_artifacts

        output_artifacts.delete_artifacts(output)
    except Exception:  # noqa: BLE001
        logger.warning("output_service: could not discard artifacts for %s", output.id)


def current_status(db: Session, output: Output) -> str:
    """The row's status as committed — another process (the API's cancel)
    may have changed it since this session loaded ``output``."""
    status = db.query(Output.status).filter(Output.id == output.id).scalar()
    return status or output.status


def report_progress(db: Session, output: Output, pct: int, message: str) -> None:
    """Record and publish generation progress. Outputters call this between
    units of work (a chapter, a slide); it is also the cancellation point:
    if the row was cancelled meanwhile it raises ``OutputCancelled``."""
    if current_status(db, output) == OutputStatus.CANCELLED.value:
        raise OutputCancelled("Cancelled by user")
    output.progress_pct = max(0, min(100, int(pct)))
    output.progress_message = (message or "")[:500]
    output.updated_at = datetime.now(timezone.utc)
    db.commit()
    _publish_progress(output)


def cancel_output(db: Session, user_id: str, output_id: str) -> Output | None:
    """Mark the caller's output cancelled and revoke its task. Returns None
    when the output is not theirs (or does not exist); raises ``OutputError``
    when it already finished."""
    row = get_output(db, user_id, output_id)
    if row is None:
        return None
    if row.status in TERMINAL_STATUSES:
        raise OutputError(f"Output cannot be cancelled (status: {row.status})")
    if row.celery_task_id:
        try:
            from app.tasks.celery_app import celery_app

            # Best effort: a solo-pool worker cannot terminate a running task,
            # which is why report_progress also checks the status.
            celery_app.control.revoke(row.celery_task_id, terminate=True)
        except Exception:  # noqa: BLE001
            logger.warning("output_service: revoke failed for output %s", output_id)
    transition_to(db, row, OutputStatus.CANCELLED, progress_message="Cancelled by user")
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Generate (driver)
# ---------------------------------------------------------------------------


def run_generation(db: Session, user: User, output: Output) -> Output:
    """Drive the lifecycle: PENDING → GENERATING → (COMPLETED|FAILED).

    Looks up the outputter for the row's kind and invokes it. Catches
    ``OutputError`` and any unexpected exception, capturing the message
    in ``error_message`` and transitioning to FAILED. Returns the
    refreshed Output row.

    Runs inside the `generate_output` Celery task (S-6.7.1), or inline for
    `POST /author/outputs?sync=true`. A row cancelled before it starts is
    left alone; a cancel during generation ends it as `cancelled` with no
    content.
    """
    outputter = get_outputter(output.kind)
    if outputter is None:
        raise NoOutputterError(
            f"No outputter registered for kind '{output.kind}'. "
            f"Registered: {list_outputters()}"
        )

    if current_status(db, output) == OutputStatus.CANCELLED.value:
        db.refresh(output)
        return output
    output.progress_pct = 5
    transition_to(db, output, OutputStatus.GENERATING, progress_message="Generating")
    # The status-change event carries no percentage; send one so a live
    # row shows 5 % rather than 0 % until the first unit of work reports.
    _publish_progress(output)
    try:
        outputter.generate(db, user, output)
    except OutputCancelled:
        logger.info("output_service: output_id=%s cancelled during generation", output.id)
        db.rollback()
        db.refresh(output)
        output.content_text = None
        output.content_path = None
        _discard_artifacts(output)
        if output.status != OutputStatus.CANCELLED.value:
            transition_to(db, output, OutputStatus.CANCELLED, progress_message="Cancelled by user")
        else:
            db.commit()
        db.refresh(output)
        return output
    except OutputSkipped as e:
        logger.info("output_service: output_id=%s skipped: %s", output.id, e)
        db.rollback()
        db.refresh(output)
        output.content_text = None
        output.content_path = None
        _discard_artifacts(output)
        transition_to(db, output, OutputStatus.SKIPPED, progress_message=str(e)[:500])
        db.refresh(output)
        return output
    except OutputError as e:
        logger.warning(
            "output_service: generation failed for output_id=%s kind=%s: %s",
            output.id,
            output.kind,
            e,
        )
        db.rollback()
        db.refresh(output)
        _discard_artifacts(output)
        transition_to(db, output, OutputStatus.FAILED, error_message=str(e), progress_message="Failed")
        db.refresh(output)
        return output
    except Exception as e:  # noqa: BLE001
        logger.exception(
            "output_service: unexpected generation failure for output_id=%s kind=%s",
            output.id,
            output.kind,
        )
        db.rollback()
        db.refresh(output)
        _discard_artifacts(output)
        transition_to(
            db,
            output,
            OutputStatus.FAILED,
            error_message=f"Unexpected error: {e!r}",
            progress_message="Failed",
        )
        db.refresh(output)
        return output

    # A cancel that landed after the outputter's last progress report must
    # still win: the user was told it stopped.
    if current_status(db, output) == OutputStatus.CANCELLED.value:
        db.rollback()
        db.refresh(output)
        _discard_artifacts(output)
        return output

    # Outputter populated content_text or content_path; mark completed.
    output.progress_pct = 100
    transition_to(db, output, OutputStatus.COMPLETED, progress_message="Done")
    db.refresh(output)
    return output
