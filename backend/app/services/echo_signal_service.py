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

from sqlalchemy import or_
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
#: A language the tagger cannot name (T-3.3.2.11). A label on what the user
#: wrote, not a language to write in: a draft is never asked for it, so
#: `routers/echo_drafts.py` lists the other four.
UNNAMED_LANGUAGE = "other"
LANGUAGES: tuple[str, ...] = ("en", "hi-Deva", "hi-Latn", "mixed", UNNAMED_LANGUAGE)
REGISTERS: tuple[str, ...] = ("intimate", "casual", "professional", "public")
ORIGINS: tuple[str, ...] = ("user", "llm", "stylometry")

#: Version of the voice-capture consent the signals panel shows. Stamped on
#: every signal so a later change of terms can tell old learning from new.
CONSENT_VERSION = "2026-10-19"

MAX_EXAMPLES = 5
MAX_EXAMPLE_CHARS = 400
MAX_VALUE_CHARS = 500
SOURCE_PREFIXES = ("note:", "share:", "qa:", "library_qa:", "history_qa:", "event:", "draft_edit:", "user")


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


def _withdrawable(q):
    """Live signals and the user's rejections. A rejection keeps its row (the
    tombstone), and so its examples; a deleted source's words must still
    leave it, or restoring it (T-3.3.1.6) would bring them back."""
    return q.filter(or_(VoiceSignal.suppressed_at.is_(None), VoiceSignal.suppressed_reason == "user"))


def withdrawable_signals(db: Session, tenant_id: str) -> list[VoiceSignal]:
    """Every signal a source withdrawal must clean: live ones and rejections."""
    return _withdrawable(db.query(VoiceSignal).filter(VoiceSignal.tenant_id == tenant_id)).all()


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
        raise SignalError("You marked this as not you earlier, so Echo will not add it again.")
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
    _sync_vectors(db, tenant_id)
    return row


def _sync_vectors(db: Session, tenant_id: str) -> None:
    """S-3.3.3: a signal's vector follows the row (a tombstone's is deleted)."""
    from app.services import echo_personal_vectors

    echo_personal_vectors.sync_soft(db, tenant_id)


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
        cleaned = _clean_value(value)
        if cleaned != row.value and row.origin != "user":
            # The user has reworded a learned signal: it is theirs now, and a
            # later run recomputing cadence must not delete it.
            row.origin = "user"
        row.value = cleaned
        row.value_key = value_key(row.value)
    row.language = new_language
    row.register = new_register
    if weight is not None:
        if not 0.0 <= weight <= 100.0:
            raise SignalError("weight must be between 0 and 100")
        row.weight = float(weight)
    db.commit()
    db.refresh(row)
    _sync_vectors(db, tenant_id)
    return row


def suppress(db: Session, tenant_id: str, signal_id: str, reason: str = "user") -> VoiceSignal:
    """"That's not me": tombstone the signal. It leaves every list and the
    export's live profile, and extraction never recreates it."""
    row = get_live(db, tenant_id, signal_id)
    row.suppressed_at = _now()
    row.suppressed_reason = reason
    db.commit()
    db.refresh(row)
    _sync_vectors(db, tenant_id)
    return row


def list_rejected(db: Session, tenant_id: str) -> list[VoiceSignal]:
    """The user's "That's not me" rejections, most recent first (T-3.3.1.6).
    A signal hidden because its sources were deleted is not a rejection and
    is not listed: new evidence brings it back on its own."""
    return (
        db.query(VoiceSignal)
        .filter(VoiceSignal.tenant_id == tenant_id, VoiceSignal.suppressed_reason == "user")
        .order_by(VoiceSignal.suppressed_at.desc(), VoiceSignal.id)
        .all()
    )


@dataclass(frozen=True)
class Restored:
    signal: VoiceSignal
    #: False when nothing the user wrote still shows the signal: the
    #: rejection is lifted, but it stays out of the profile (as
    #: ``source_deleted``) until new evidence re-derives it.
    live: bool


def restore(db: Session, tenant_id: str, signal_id: str) -> Restored:
    """Undo "That's not me" (T-3.3.1.6): clear the tombstone, so the signal
    is in the profile again and re-adding or re-learning it is no longer
    refused.

    The evidence is re-checked first. Before T-3.3.1.6 a withdrawal skipped
    rejected signals, so a rejection can still cite a source the user has
    since deleted or edited, and hold its words: a ref that is no longer a
    live input leaves the signal, and so does an example its source no longer
    contains (``_still_evidence``). A learned signal left with no evidence
    becomes ``source_deleted`` rather than live.

    Every other rejection of the same signal (same type, wording and
    language: rewording one signal into another's words makes a twin) is
    lifted with it, its checked evidence merged in and its row dropped;
    otherwise the twin would go on refusing the restored signal. If an equal
    live signal exists, that one is kept and the tombstones are dropped.
    Commits."""
    row = (
        db.query(VoiceSignal)
        .filter(
            VoiceSignal.id == signal_id,
            VoiceSignal.tenant_id == tenant_id,
            VoiceSignal.suppressed_reason == "user",
        )
        .first()
    )
    if row is None:
        raise SignalNotFound("Signal not found")
    same_key = db.query(VoiceSignal).filter(
        VoiceSignal.tenant_id == tenant_id,
        VoiceSignal.signal_type == row.signal_type,
        VoiceSignal.value_key == row.value_key,
        VoiceSignal.language.is_(None) if row.language is None else VoiceSignal.language == row.language,
        VoiceSignal.id != row.id,
    )
    twins = same_key.filter(VoiceSignal.suppressed_reason == "user").order_by(VoiceSignal.created_at, VoiceSignal.id).all()
    same = _live(same_key).first()
    if same is not None:
        for r in (row, *twins):
            db.delete(r)
        db.commit()
        db.refresh(same)
        _sync_vectors(db, tenant_id)
        return Restored(same, True)

    own = _json_list(row.derived_from)
    sources = list(own)
    examples = _json_list(row.examples_json)
    for twin in twins:
        sources += [s for s in _json_list(twin.derived_from) if s not in sources]
        examples += [e for e in _json_list(twin.examples_json) if e not in examples]
    sources, examples = _still_evidence(db, tenant_id, sources, examples)
    gained = len([s for s in sources if s not in own])
    lost = len([s for s in own if s not in sources])
    row.derived_from = json.dumps(sources)
    row.examples_json = json.dumps(examples[:MAX_EXAMPLES], ensure_ascii=False)
    if gained or lost:
        row.weight = max(0.0, float(row.weight) + gained - lost) or 0.5
    for twin in twins:
        db.delete(twin)
    if sources:
        row.suppressed_at = None
        row.suppressed_reason = None
        from app.services import echo_signal_extraction

        # A twin's shares now feed this row: deleting one must withdraw it.
        echo_signal_extraction.record_on_shares(db, tenant_id, row)
    else:
        row.suppressed_reason = "source_deleted"
    db.commit()
    db.refresh(row)
    _sync_vectors(db, tenant_id)
    return Restored(row, row.suppressed_at is None)


def _still_evidence(db: Session, tenant_id: str, sources: list[str], examples: list) -> tuple[list[str], list[dict]]:
    """The part of a signal's evidence that still stands: refs that are live
    inputs (``user``, typed on the panel, always is) and examples whose
    source still contains their words. A ref whose every example on the
    signal is gone was edited away and leaves too (as an edited input is
    withdrawn); a ref with no example kept on the signal stays while the
    input is live, since it shows no words."""
    from app.services import echo_signal_extraction

    examples = [e for e in examples if isinstance(e, dict)]
    texts = echo_signal_extraction.live_evidence_texts(
        db, tenant_id, [*sources, *(str(e.get("source", "")) for e in examples)]
    )

    def stands(e: dict) -> bool:
        src = str(e.get("source", ""))
        if src == "user":
            return True
        return src in texts and echo_signal_extraction.still_quotes(str(e.get("text", "")), texts[src])

    kept_examples = [e for e in examples if stands(e)]
    cited = {str(e.get("source", "")) for e in examples}
    shown = {str(e.get("source", "")) for e in kept_examples}
    kept_sources = [s for s in sources if s == "user" or (s in texts and (s not in cited or s in shown))]
    return kept_sources, kept_examples


@dataclass
class RejectedSweep:
    """What ``sweep_rejected_evidence`` found: rejections read, how many held
    stale evidence, and the examples and refs that do not stand."""

    rejected: int = 0
    stale: int = 0
    examples: int = 0
    refs: int = 0

    def add(self, other: "RejectedSweep") -> None:
        self.rejected += other.rejected
        self.stale += other.stale
        self.examples += other.examples
        self.refs += other.refs


def stale_rejected_evidence(db: Session, tenant_id: str) -> dict[str, tuple[list[str], list[dict]]]:
    """By signal id, each of the tenant's rejections whose stored evidence no
    longer all stands, with the refs and examples that do. Read-only. Rows the
    withdrawal has kept clean are not in it."""
    out: dict[str, tuple[list[str], list[dict]]] = {}
    for row in list_rejected(db, tenant_id):
        sources, examples = _json_list(row.derived_from), _json_list(row.examples_json)
        kept = _still_evidence(db, tenant_id, sources, examples)
        if kept != (sources, examples):
            out[row.id] = kept
    return out


def sweep_rejected_evidence(db: Session, tenant_id: str, *, write: bool) -> RejectedSweep:
    """T-3.3.1.7: clear from the tenant's rejections what ``restore`` would
    drop, at rest. A rejection stays one, whatever is left; its weight drops
    by the refs it lost, as a withdrawal counts it, so a later restore comes
    to the same signal. Commits only with ``write``. Idempotent."""
    rows = {r.id: r for r in list_rejected(db, tenant_id)}
    stale = stale_rejected_evidence(db, tenant_id)
    found = RejectedSweep(rejected=len(rows), stale=len(stale))
    for signal_id, (sources, examples) in stale.items():
        row = rows[signal_id]
        lost = len(_json_list(row.derived_from)) - len(sources)
        found.refs += lost
        found.examples += len(_json_list(row.examples_json)) - len(examples)
        if write:
            row.derived_from = json.dumps(sources)
            row.examples_json = json.dumps(examples, ensure_ascii=False)
            if lost:
                row.weight = max(0.0, float(row.weight) - lost) or 0.5
    if write and stale:
        db.commit()
    return found


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
    live signal of the tenant is checked. The user's rejections are cleaned
    too and stay rejections, so a later restore cannot bring back a deleted
    source's words. Does not commit."""
    q = _withdrawable(db.query(VoiceSignal).filter(VoiceSignal.tenant_id == tenant_id))
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
        if not remaining and row.suppressed_reason != "user":
            row.suppressed_at = _now()
            row.suppressed_reason = "source_deleted"
            suppressed += 1
        else:
            # A rejection stays one, whatever is left (see _withdrawable).
            row.weight = max(0.0, float(row.weight) - 1.0) or 0.5
            updated += 1
    return SourceWithdrawal(updated, suppressed)


def withdraw_sources(db: Session, tenant_id: str, source_refs: Iterable[str]) -> SourceWithdrawal:
    """``withdraw_source`` for many refs in ONE pass over the tenant's live
    signals and rejections: a connector revoke or an import undo can remove
    thousands of events at once. Does not commit."""
    refs = set(source_refs)
    if not refs:
        return SourceWithdrawal(0, 0)
    updated = suppressed = 0
    for row in withdrawable_signals(db, tenant_id):
        sources = _json_list(row.derived_from)
        gone = [s for s in sources if s in refs]
        if not gone:
            continue
        remaining = [s for s in sources if s not in refs]
        row.derived_from = json.dumps(remaining)
        row.examples_json = json.dumps([e for e in _json_list(row.examples_json) if e.get("source") not in refs])
        if not remaining and row.suppressed_reason != "user":
            row.suppressed_at = _now()
            row.suppressed_reason = "source_deleted"
            suppressed += 1
        else:
            # A rejection stays one, whatever is left (see _withdrawable).
            row.weight = max(0.0, float(row.weight) - len(gone)) or 0.5
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
