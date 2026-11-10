"""Author Studio output service — I-6 foundation.

Three layers:

1. **CRUD** on Output rows (``create``, ``get``, ``list``, ``delete``).
2. **Outputter Protocol** + registry — concrete outputters implement
   ``generate(db, user, output) -> None`` which transitions
   ``output.status`` from ``generating`` → ``completed`` (writing
   ``content_text`` or ``content_path``) or ``failed`` (writing
   ``error_message``).
3. **Status state machine** — `pending` → `generating` → `completed`
   | `failed` | `skipped`, and `cancelled` from either live state. The
   service exposes transition helpers so concrete outputters don't manage
   status directly. An ended output stays ended (T-5.2.34): every status and
   progress write is one conditional ``UPDATE`` that refuses a row in
   ``TERMINAL_STATUSES``, and its event is published only once it is written.

S-6.7.1 moved generation into the Celery worker (`tasks/output_tasks.py`):
`POST /author/outputs` writes a `pending` row and dispatches
`generate_output` on the owner's tier queue. Every status change and every
``report_progress`` call is published on `job_progress:{output_id}`, the
channel job progress already uses, so the WebSocket manager and the
frontend's `wsClient` needed no new channel. Cancellation is cooperative:
`cancel_output` marks the row, then revokes the task, and the next
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
from app.utils.log_redaction import error_summary, provider_error_text
from app.utils.shared_url_log import traceback_without_text

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


class OutputStopped(OutputError):
    """Raised by ``report_progress`` when the row ended meanwhile, but not by a
    cancel: another delivery of the same task completed or failed it (T-5.2.34).
    The run stops. A completed row keeps its end, its content and its folder;
    a failed or skipped one keeps no content, citations or files, this run's
    included. Files are written straight into the output's one folder, so a
    file this run wrote after the other delivery completed, and before this
    report, has already replaced that delivery's (the two-live-deliveries case,
    T-5.2.29, which no write here can refuse)."""


class OutputSkipped(OutputError):
    """Raised by an outputter that found nothing to make (S-6.4.1). The row
    ends ``skipped`` with this message as its progress message, and no
    content or files."""


class OutputUnavailable(OutputError):
    """A requested format needs a converter this server does not have
    (S-6.1.5: a book's PDF). The router answers 501 with the message, which
    says what to install; in the worker it fails the row like any error."""


class OutputSourceNotFound(OutputError):
    """A chosen source is not in the caller's library (S-6.3.2: a document
    they cannot see). Raised by an outputter's ``check_sources`` before the
    row exists; the router answers 404, so another tenant's document reads
    exactly like one that does not exist (D-063)."""


class OutputSourceNotReady(OutputError):
    """A chosen source is the caller's but lacks what the kind is built from
    (S-6.3.2: a document with no knowledge report yet). The router answers
    409 with the message, which says what to do first."""


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

    # Optional hooks the router looks up with ``getattr`` before any row is
    # written: ``prepare_parameters(params) -> params`` (S-6.1.5) and
    # ``check_sources(db, user, source_ids) -> None`` (S-6.3.2), which raises
    # ``OutputSourceNotFound`` (404) or ``OutputSourceNotReady`` (409).

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


_NO_CONTENT: dict[str, Any] = {"content_text": None, "content_path": None}


def _write_unless_ended(db: Session, output: Output, values: dict, *, drop_content: bool = False) -> bool:
    """Write ``values`` to the output's row unless the row has ended
    (``TERMINAL_STATUSES``), in one conditional ``UPDATE``, and commit.

    The caller's own pending changes (the content an outputter set, its
    citations) are flushed first, in the same transaction, so the test and
    every write are one step: a cancel that commits before it is seen and
    nothing is written, and one that comes after finds the row ended. Refused,
    the transaction is rolled back, those pending changes included, so an
    ended row never takes a later write. ``output`` is refreshed from the row
    either way. Returns whether the row was written (T-5.2.34).

    ``drop_content`` is for a write that ends the output other than
    ``completed``: the same write clears ``content_text`` and ``content_path``
    and the same transaction deletes the citations, so the row never reads
    ended with what a run had committed before it (a book commits its
    manuscript with the progress reports of its EPUB and PDF).
    """
    db.flush()
    values = {**values, "updated_at": datetime.now(timezone.utc)}
    if drop_content:
        values.update(_NO_CONTENT)
    written = (
        db.query(Output)
        .filter(Output.id == output.id, Output.status.notin_(TERMINAL_STATUSES))
        .update(values, synchronize_session=False)
    )
    if written != 1:
        db.rollback()
        db.refresh(output)
        return False
    if drop_content:
        from app.services import output_citation_service

        output_citation_service.delete_citations(db, output.id)
    db.commit()
    db.refresh(output)
    return True


def _clear_unfinished(db: Session, output: Output) -> None:
    """An output that ended other than ``completed`` keeps no content,
    citations or files (S-6.7.2, T-5.2.34), whoever ended it.

    For the run that finds its output ended by someone else: a cancel, or
    another delivery of its task that failed or skipped it. The clear is one
    write conditional on the row still holding the end ``output`` was refreshed
    with, which it always will, since nothing writes over an ended row; and the
    files are removed, this run's included, since a run writes files straight
    into the output's folder (a PDF printed after its last progress report).
    A row another delivery completed is left as it is: its content, its
    citations and the files in its folder are that end's.
    """
    ended = output.status
    if ended not in TERMINAL_STATUSES or ended == OutputStatus.COMPLETED.value:
        return
    db.rollback()
    cleared = (
        db.query(Output)
        .filter(Output.id == output.id, Output.status == ended)
        .update(dict(_NO_CONTENT), synchronize_session=False)
    )
    if cleared == 1:
        from app.services import output_citation_service

        output_citation_service.delete_citations(db, output.id)
    db.commit()
    db.refresh(output)
    _discard_artifacts(output)


def transition_to(
    db: Session,
    output: Output,
    new_status: OutputStatus | str,
    *,
    error_message: str | None = None,
    progress_message: str | None = None,
    drop_content: bool = False,
) -> bool:
    """Write ``status`` (and optionally ``error_message`` /
    ``progress_message``) unless the output has already ended, commit, and only
    then publish the change on `job_progress:{output_id}`. ``drop_content``
    clears the content and citations in the same write, for an end other than
    ``completed`` (``_write_unless_ended``).

    T-5.2.34: an output that ended stays ended, as a run does: a cancel never
    writes over a finished output, a run never writes ``completed`` or
    ``failed`` over a cancel, and no page is told of an end that did not
    happen. Refused, nothing is written or published, the caller's pending
    changes included, and ``output`` holds the row as it is. Returns whether
    the change was written. The open page drops events for an output it holds
    as ended, which is sound only while every end goes out after the write
    that made it, as here."""
    old = output.status
    values: dict[str, Any] = {
        "status": new_status.value if isinstance(new_status, OutputStatus) else new_status,
    }
    if error_message is not None:
        values["error_message"] = error_message
    if progress_message is not None:
        values["progress_message"] = progress_message[:500]
    if not _write_unless_ended(db, output, values, drop_content=drop_content):
        logger.info(
            "output_service: output_id=%s is already %s; %s not written",
            output.id, output.status, values["status"],
        )
        return False
    _publish_status(output.id, old, output.status, output.progress_message or output.status)
    return True


def _discard_artifacts(output: Output) -> None:
    """A run that did not complete leaves no files behind (S-6.7.2)."""
    try:
        from app.services import output_artifacts

        output_artifacts.delete_artifacts(output)
    except Exception:  # noqa: BLE001
        logger.warning("output_service: could not discard artifacts for %s", output.id)


def record_queued(db: Session, output: Output, task_id: str | None) -> None:
    """After dispatch: keep the task's id, and say ``Queued`` while the output
    is still ``pending``, then commit.

    The worker can take the task and end the output before the route gets
    here (an outputter that fails on its first step), so ``Queued`` is one
    write conditional on ``pending`` (T-5.2.34): an output that started or
    ended keeps the progress message its run wrote. The task id is kept
    whatever the status, as the task itself does when it starts; it writes no
    status or progress and publishes nothing."""
    db.query(Output).filter(Output.id == output.id).update(
        {"celery_task_id": task_id}, synchronize_session=False
    )
    db.query(Output).filter(Output.id == output.id, Output.status == OutputStatus.PENDING.value).update(
        {"progress_message": "Queued", "updated_at": datetime.now(timezone.utc)}, synchronize_session=False
    )
    db.commit()
    db.refresh(output)


def report_progress(db: Session, output: Output, pct: int, message: str) -> None:
    """Record and publish generation progress. Outputters call this between
    units of work (a chapter, a slide); it is also the cancellation point:
    if the row was cancelled meanwhile it raises ``OutputCancelled``.

    T-5.2.34: written first, in the conditional write ``transition_to`` uses,
    and published only once written, as a run's progress is (T-5.2.21). A
    read before the write, as here until then, let a cancel land between the
    two, and the line went out after it. Refused, nothing is published: a
    cancelled row raises ``OutputCancelled``, any other end ``OutputStopped``.
    """
    values = {
        "progress_pct": max(0, min(100, int(pct))),
        "progress_message": (message or "")[:500],
    }
    if not _write_unless_ended(db, output, values):
        if output.status == OutputStatus.CANCELLED.value:
            raise OutputCancelled("Cancelled by user")
        raise OutputStopped(f"The output is already {output.status}")
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
    # T-5.2.34: only while the output has not ended, in one conditional write,
    # announced only once that write has committed, as a run's cancel is
    # (T-5.2.22, T-5.2.30). An output that finished between the read above and
    # this write keeps its end, and the cancel answers what it would have a
    # moment later. A second cancel that finds it cancelled by the first
    # answers with the cancelled row, as before, and publishes nothing. The
    # same write clears what the run had committed so far (a book's manuscript
    # and citations go in with its EPUB and PDF progress reports), so a
    # cancelled output serves no content from the moment it says cancelled,
    # not only once the run notices; the run removes its files then.
    transition_to(db, row, OutputStatus.CANCELLED, progress_message="Cancelled by user", drop_content=True)
    if row.status != OutputStatus.CANCELLED.value:
        raise OutputError(f"Output cannot be cancelled (status: {row.status})")
    # Revoked only once the row says cancelled: terminating a task that is
    # closing an output that just finished could lose the usage its scope
    # writes on the way out (D-163's reasoning for runs).
    if row.celery_task_id:
        try:
            from app.tasks.celery_app import celery_app

            # Best effort: a solo-pool worker cannot terminate a running task,
            # which is why report_progress also checks the status.
            celery_app.control.revoke(row.celery_task_id, terminate=True)
        except Exception:  # noqa: BLE001
            logger.warning("output_service: revoke failed for output %s", output_id)
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
    `POST /author/outputs?sync=true`. A row that ended before it starts
    (cancelled, or finished by another delivery of its task) is left alone;
    a cancel during generation, or after its last progress report, ends it
    as `cancelled` with no content, citations or files, including what the
    run committed with its progress reports, and so does a failure or a skip
    (T-5.2.34).

    E-5.2: the whole run is metered against ``user`` (feature author), from
    the task, the inline route and a newsletter issue alike. The scope closes
    after the rollback a failed or cancelled run does, so a cancel never has
    half its content committed by the meter.
    """
    from app.services import usage_service

    with usage_service.metered(db, user.id, feature="author"):
        return _run_generation(db, user, output)


def _run_generation(db: Session, user: User, output: Output) -> Output:
    outputter = get_outputter(output.kind)
    if outputter is None:
        raise NoOutputterError(
            f"No outputter registered for kind '{output.kind}'. "
            f"Registered: {list_outputters()}"
        )

    # T-5.2.34: the write is the check. An output cancelled before it starts,
    # or finished by another delivery of its task, is left alone and nothing
    # is published, the 5 % below included.
    output.progress_pct = 5
    if not transition_to(db, output, OutputStatus.GENERATING, progress_message="Generating"):
        return output
    # The status-change event carries no percentage; send one so a live
    # row shows 5 % rather than 0 % until the first unit of work reports.
    _publish_progress(output)
    try:
        outputter.generate(db, user, output)
    except OutputCancelled:
        logger.info("output_service: output_id=%s cancelled during generation", output.id)
        db.rollback()
        db.refresh(output)
        _end_unfinished(db, output, OutputStatus.CANCELLED, progress_message="Cancelled by user")
        return output
    except OutputStopped:
        # Another delivery of the task ended the row. A completed end keeps its
        # content and files; any other end keeps none, this run's files
        # included.
        logger.info("output_service: output_id=%s ended meanwhile as %s; this run stops", output.id, output.status)
        db.rollback()
        db.refresh(output)
        _clear_unfinished(db, output)
        return output
    except OutputSkipped as e:
        logger.info("output_service: output_id=%s skipped: %s", output.id, e)
        db.rollback()
        db.refresh(output)
        _end_unfinished(db, output, OutputStatus.SKIPPED, progress_message=provider_error_text(e)[:500])
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
        # T-5.6.17: an OutputError is our own sentence, but one can carry a
        # model call's words (a deck's failed outline), so they are scrubbed.
        _end_unfinished(db, output, OutputStatus.FAILED, error_message=provider_error_text(e), progress_message="Failed")
        return output
    except Exception as e:  # noqa: BLE001
        # T-4.11.4.4: by its frames and type. A database error or a renderer's
        # quotes what it was given: the book's, deck's or issue's text, and
        # the title the user typed. The row keeps the words for its owner.
        logger.error(
            "output_service: unexpected generation failure for output_id=%s kind=%s: %s",
            output.id,
            output.kind,
            traceback_without_text(e),
        )
        db.rollback()
        db.refresh(output)
        _end_unfinished(
            db,
            output,
            OutputStatus.FAILED,
            error_message=f"Unexpected error: {error_summary(e)}",
            progress_message="Failed",
        )
        return output

    # Outputter populated content_text or content_path; mark completed. A
    # cancel that landed after the outputter's last progress report still
    # wins, since the user was told it stopped: the conditional write finds the
    # row cancelled and rolls back this run's uncommitted content with it
    # (T-5.2.34). Until then a read stood here, and a cancel landing between it
    # and the write was overwritten by `completed`. What the run committed with
    # its progress reports went with the cancel's own write, and the files it
    # wrote since go here, as they do when another delivery failed or skipped
    # the output meanwhile.
    output.progress_pct = 100
    if not transition_to(db, output, OutputStatus.COMPLETED, progress_message="Done"):
        _clear_unfinished(db, output)
        return output
    return output


def _end_unfinished(db: Session, output: Output, status: OutputStatus, **fields: str) -> None:
    """End a run that did not complete as ``status``, unless the output has
    already ended. Either way an output that did not complete keeps no content,
    citations or files (S-6.7.2): this run's end clears them in its own write;
    an end someone else wrote (a cancel, another delivery's failure) has them
    cleared after it. An output another delivery of the task completed keeps
    the content and files its end wrote."""
    if transition_to(db, output, status, drop_content=True, **fields):
        _discard_artifacts(output)
        return
    _clear_unfinished(db, output)
