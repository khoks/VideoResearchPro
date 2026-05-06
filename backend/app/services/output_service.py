"""Author Studio output service — I-6 foundation.

Three layers:

1. **CRUD** on Output rows (``create``, ``get``, ``list``, ``delete``).
2. **Outputter Protocol** + registry — concrete outputters implement
   ``generate(db, user, output) -> None`` which transitions
   ``output.status`` from ``generating`` → ``completed`` (writing
   ``content_text`` or ``content_path``) or ``failed`` (writing
   ``error_message``).
3. **Status state machine** — `pending` → `generating` → `completed`
   | `failed`. The service exposes transition helpers so concrete
   outputters don't manage status directly.

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


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OutputError(RuntimeError):
    pass


class UnsupportedKindError(OutputError):
    pass


class NoOutputterError(OutputError):
    pass


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
    db.delete(row)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def transition_to(
    db: Session,
    output: Output,
    new_status: OutputStatus | str,
    *,
    error_message: str | None = None,
) -> None:
    """Update ``output.status`` and optionally ``error_message``. The
    state machine isn't strictly enforced (any → any transition allowed)
    so callers can re-try generation; outputter-driven retry is a
    future concern."""
    output.status = new_status.value if isinstance(new_status, OutputStatus) else new_status
    if error_message is not None:
        output.error_message = error_message
    output.updated_at = datetime.now(timezone.utc)
    db.commit()


# ---------------------------------------------------------------------------
# Generate (driver)
# ---------------------------------------------------------------------------


def run_generation(db: Session, user: User, output: Output) -> Output:
    """Drive the lifecycle: PENDING → GENERATING → (COMPLETED|FAILED).

    Looks up the outputter for the row's kind and invokes it. Catches
    ``OutputError`` and any unexpected exception, capturing the message
    in ``error_message`` and transitioning to FAILED. Returns the
    refreshed Output row.

    Synchronous for v1. A future PR can wrap this in a Celery task
    when generation gets expensive (LLM-driven book composition).
    """
    outputter = get_outputter(output.kind)
    if outputter is None:
        raise NoOutputterError(
            f"No outputter registered for kind '{output.kind}'. "
            f"Registered: {list_outputters()}"
        )

    transition_to(db, output, OutputStatus.GENERATING)
    try:
        outputter.generate(db, user, output)
    except OutputError as e:
        logger.warning(
            "output_service: generation failed for output_id=%s kind=%s: %s",
            output.id,
            output.kind,
            e,
        )
        transition_to(db, output, OutputStatus.FAILED, error_message=str(e))
        db.refresh(output)
        return output
    except Exception as e:  # noqa: BLE001
        logger.exception(
            "output_service: unexpected generation failure for output_id=%s kind=%s",
            output.id,
            output.kind,
        )
        transition_to(
            db,
            output,
            OutputStatus.FAILED,
            error_message=f"Unexpected error: {e!r}",
        )
        db.refresh(output)
        return output

    # Outputter populated content_text or content_path; mark completed.
    transition_to(db, output, OutputStatus.COMPLETED)
    db.refresh(output)
    return output
