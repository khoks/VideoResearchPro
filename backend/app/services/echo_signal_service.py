"""Echo voice and personality signals (S-3.3.1 / E-3.3).

Rows in ``voice_signals``, never a prompt blob (plan:
docs/plans/l3-echo-personal-brain.md, Domain 3). This module owns the
closed vocabularies, the CRUD the signals panel uses, the tombstone that
keeps a rejected signal from coming back, the clean-up when a source is
withdrawn, and the profile export.

Rules carried from the decisions:

- **Only the user's own words** feed a signal (D-089 item 1). Examples and
  provenance therefore only ever name notes, the user's questions, shares
  marked ``author_is_tenant`` and signals the user typed. Extraction
  (S-3.3.2) enforces this at the input; ``add_example`` refuses a share
  reference the caller has not checked.
- **A tombstone is permanent for the user's rejection.** ``suppress``
  (reason ``user``) keeps the row; ``is_suppressed`` is what extraction asks
  before it writes. A signal whose every source was deleted is suppressed
  with reason ``source_deleted`` and may be re-derived from new evidence.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.voice_signal import VoiceSignal

logger = logging.getLogger(__name__)

# personal-brain.md Domain 3, both layers, in display order.
STYLE_TYPES: tuple[str, ...] = (
    "vocabulary",
    "cadence",
    "framing",
    "recurring_reference",
    "formality_register",
    "register_per_audience",
)
PERSONALITY_TYPES: tuple[str, ...] = (
    "trusted_conclusion",
    "preferred_solution",
    "recommendation_lens",
    "apprehension",
    "methodology",
    "topic_emphasis",
    "perception_lens",
    "interest",
)
SIGNAL_TYPES: tuple[str, ...] = STYLE_TYPES + PERSONALITY_TYPES
LANGUAGES: tuple[str, ...] = ("en", "hi-Deva", "hi-Latn", "mixed")
REGISTERS: tuple[str, ...] = ("intimate", "casual", "professional", "public")
ORIGINS: tuple[str, ...] = ("user", "llm", "stylometry")

#: Version of the voice-capture consent the signals panel shows. Stamped on
#: every signal so a later change of terms can tell old learning from new.
CONSENT_VERSION = "2026-10-19"

MAX_EXAMPLES = 5
MAX_EXAMPLE_CHARS = 400
MAX_VALUE_CHARS = 500
SOURCE_PREFIXES = ("note:", "share:", "qa:", "library_qa:", "history_qa:", "user")


class SignalError(ValueError):
    """A request the signals API cannot accept (422)."""


class SignalNotFound(LookupError):
    """No live signal with that id for this tenant (404)."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def value_key(value: str) -> str:
    """The merge and tombstone key: casefolded, whitespace collapsed, trimmed
    of surrounding quotes and full stops, at most 300 characters."""
    key = " ".join((value or "").casefold().split()).strip(" \"'“”‘’.")
    return key[:300]


def _json_list(raw: str | None) -> list:
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _check(signal_type: str, language: str | None, register: str | None) -> None:
    if signal_type not in SIGNAL_TYPES:
        raise SignalError(f"signal_type must be one of: {', '.join(SIGNAL_TYPES)}")
    if language is not None and language not in LANGUAGES:
        raise SignalError(f"language must be one of: {', '.join(LANGUAGES)}")
    if register is not None and register not in REGISTERS:
        raise SignalError(f"register must be one of: {', '.join(REGISTERS)}")


def _clean_value(value: str) -> str:
    v = " ".join((value or "").split())
    if not v:
        raise SignalError("value must not be empty")
    if len(v) > MAX_VALUE_CHARS:
        raise SignalError(f"value is longer than {MAX_VALUE_CHARS} characters")
    return v


def clean_example(text: str, source: str, at: str | None = None) -> dict[str, Any]:
    if not any(source == p or source.startswith(p) for p in SOURCE_PREFIXES):
        raise SignalError(f"unknown example source {source!r}")
    t = " ".join((text or "").split())[:MAX_EXAMPLE_CHARS]
    if not t:
        raise SignalError("an example needs text")
    return {"text": t, "source": source, **({"at": at} if at else {})}


# ---------------------------------------------------------------------------
# Reads


def _live(q):
    return q.filter(VoiceSignal.suppressed_at.is_(None))


def list_signals(
    db: Session,
    tenant_id: str,
    *,
    signal_type: str | None = None,
    language: str | None = None,
    include_suppressed: bool = False,
) -> list[VoiceSignal]:
    q = db.query(VoiceSignal).filter(VoiceSignal.tenant_id == tenant_id)
    if not include_suppressed:
        q = _live(q)
    if signal_type:
        q = q.filter(VoiceSignal.signal_type == signal_type)
    if language:
        q = q.filter(VoiceSignal.language == language)
    order = {t: i for i, t in enumerate(SIGNAL_TYPES)}
    rows = q.all()
    rows.sort(key=lambda r: (order.get(r.signal_type, 99), -r.weight, r.created_at))
    return rows


def get_live(db: Session, tenant_id: str, signal_id: str) -> VoiceSignal:
    row = _live(db.query(VoiceSignal).filter(VoiceSignal.id == signal_id, VoiceSignal.tenant_id == tenant_id)).first()
    if row is None:
        raise SignalNotFound("Signal not found")
    return row


def is_suppressed(db: Session, tenant_id: str, signal_type: str, value: str, language: str | None) -> bool:
    """Did the user reject this signal? Extraction asks before writing.
    A ``source_deleted`` suppression does not count: new evidence may
    re-derive what the user never rejected."""
    return (
        db.query(VoiceSignal.id)
        .filter(
            VoiceSignal.tenant_id == tenant_id,
            VoiceSignal.signal_type == signal_type,
            VoiceSignal.value_key == value_key(value),
            VoiceSignal.language.is_(None) if language is None else VoiceSignal.language == language,
            VoiceSignal.suppressed_reason == "user",
        )
        .first()
        is not None
    )


def to_dict(row: VoiceSignal) -> dict[str, Any]:
    return {
        "id": row.id,
        "signal_type": row.signal_type,
        "layer": "style" if row.signal_type in STYLE_TYPES else "personality",
        "value": row.value,
        "weight": round(float(row.weight), 3),
        "examples": _json_list(row.examples_json),
        "language": row.language,
        "register": row.register,
        "derived_from": _json_list(row.derived_from),
        "origin": row.origin,
        "consent_version": row.consent_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "suppressed_at": row.suppressed_at,
        "suppressed_reason": row.suppressed_reason,
    }


# ---------------------------------------------------------------------------
# Writes


def create(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    signal_type: str,
    value: str,
    language: str | None = None,
    register: str | None = None,
    examples: Iterable[dict] | None = None,
    origin: str = "user",
    weight: float = 1.0,
) -> VoiceSignal:
    """A signal the user states about themselves on the panel (origin
    ``user``). Refused when the user already rejected the same signal."""
    _check(signal_type, language, register)
    v = _clean_value(value)
    if origin not in ORIGINS:
        raise SignalError(f"origin must be one of: {', '.join(ORIGINS)}")
    if is_suppressed(db, tenant_id, signal_type, v, language):
        raise SignalError("You marked this signal as not you. Remove that first if it is.")
    cleaned = [clean_example(e.get("text", ""), e.get("source", "user"), e.get("at")) for e in (examples or [])]
    row = VoiceSignal(
        tenant_id=tenant_id,
        user_id=user_id,
        signal_type=signal_type,
        value=v,
        value_key=value_key(v),
        weight=float(weight),
        examples_json=json.dumps(cleaned[:MAX_EXAMPLES]),
        language=language,
        register=register,
        derived_from=json.dumps(["user"] if origin == "user" else sorted({e["source"] for e in cleaned})),
        origin=origin,
        consent_version=CONSENT_VERSION,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


_UNSET: Any = object()


def update(
    db: Session,
    tenant_id: str,
    signal_id: str,
    *,
    value: str | None = None,
    language: Any = _UNSET,
    register: Any = _UNSET,
    weight: float | None = None,
) -> VoiceSignal:
    """The user corrects a signal: its wording, its language or register,
    how much it weighs. The type is fixed; a different type is a new signal."""
    row = get_live(db, tenant_id, signal_id)
    new_language = row.language if language is _UNSET else language
    new_register = row.register if register is _UNSET else register
    _check(row.signal_type, new_language, new_register)
    if value is not None:
        row.value = _clean_value(value)
        row.value_key = value_key(row.value)
    row.language = new_language
    row.register = new_register
    if weight is not None:
        if not 0.0 <= weight <= 100.0:
            raise SignalError("weight must be between 0 and 100")
        row.weight = float(weight)
    db.commit()
    db.refresh(row)
    return row


def suppress(db: Session, tenant_id: str, signal_id: str, reason: str = "user") -> VoiceSignal:
    """"That's not me": tombstone the signal. It leaves every list and the
    export's live profile, and extraction never recreates it."""
    row = get_live(db, tenant_id, signal_id)
    row.suppressed_at = _now()
    row.suppressed_reason = reason
    db.commit()
    db.refresh(row)
    return row


@dataclass(frozen=True)
class SourceWithdrawal:
    updated: int
    suppressed: int


def withdraw_source(db: Session, tenant_id: str, source_ref: str, *, signal_ids: Iterable[str] | None = None) -> SourceWithdrawal:
    """A source the user deleted (a share, a withdrawn note) stops counting.

    Its examples and provenance leave every live signal that cites it; a
    signal left with no source at all (and that the user did not type) is
    suppressed as ``source_deleted``. ``signal_ids`` narrows the scan to the
    ids a share recorded in ``derived_signal_ids_json``; without it every
    live signal of the tenant is checked. Does not commit."""
    q = _live(db.query(VoiceSignal).filter(VoiceSignal.tenant_id == tenant_id))
    ids = list(signal_ids or [])
    if signal_ids is not None:
        if not ids:
            return SourceWithdrawal(0, 0)
        q = q.filter(VoiceSignal.id.in_(ids))
    updated = suppressed = 0
    for row in q.all():
        sources = _json_list(row.derived_from)
        if source_ref not in sources:
            continue
        remaining = [s for s in sources if s != source_ref]
        examples = [e for e in _json_list(row.examples_json) if e.get("source") != source_ref]
        row.derived_from = json.dumps(remaining)
        row.examples_json = json.dumps(examples)
        if not remaining:
            row.suppressed_at = _now()
            row.suppressed_reason = "source_deleted"
            suppressed += 1
        else:
            row.weight = max(0.0, float(row.weight) - 1.0) or 0.5
            updated += 1
    return SourceWithdrawal(updated, suppressed)


# ---------------------------------------------------------------------------
# Export


def export_profile(db: Session, tenant_id: str) -> dict[str, Any]:
    """The user's live profile as JSON: every signal with its examples and
    provenance, grouped by layer. Rejected signals are listed by type and
    wording only, so the user can see what they told Echo to forget. The
    whole-brain archive (``/echo/export``) carries every column of every row."""
    live = list_signals(db, tenant_id)
    rejected = [
        r
        for r in list_signals(db, tenant_id, include_suppressed=True)
        if r.suppressed_reason == "user"
    ]
    return {
        "format": "pratidhvani-voice-profile",
        "version": 1,
        "exported_at": _now().isoformat() + "Z",
        "consent_version": CONSENT_VERSION,
        "style": [_export_row(r) for r in live if r.signal_type in STYLE_TYPES],
        "personality": [_export_row(r) for r in live if r.signal_type in PERSONALITY_TYPES],
        "rejected": [{"signal_type": r.signal_type, "value": r.value, "language": r.language} for r in rejected],
    }


def _export_row(r: VoiceSignal) -> dict[str, Any]:
    d = to_dict(r)
    for k in ("id", "layer", "suppressed_at", "suppressed_reason", "updated_at"):
        d.pop(k, None)
    d["created_at"] = r.created_at.isoformat() + "Z"
    return d
