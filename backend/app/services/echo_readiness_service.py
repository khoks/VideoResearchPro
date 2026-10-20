"""Echo readiness v2: the five-domain gate (S-3.5.1).

Echo stays quiet until it has enough of the user to echo them well
(`personal-brain.md` § Cold-start). This module measures that from the
stores themselves, every time; nothing here is a stored flag or a constant
answer. Each domain reports its criteria, how far along it is, and what is
missing **in words**, so the page can say "Write 18 more facts about
yourself" instead of showing a bare percentage.

| Domain | Store | Criteria (settings) |
|---|---|---|
| 1 Facts | `personal_context`, `source = 'manual'` | count, distinct kinds |
| 2 Activity | `activity_events`, every connector and import but `internal` | count, days spanned |
| 3 Signals | `voice_signals`, live (not suppressed) | count, distinct types |
| 3 Voice | live notes + shares the user marked as their own words | per-script floor (pieces or words), centroid stability |
| 5 Shares | `shares_inbox` | count, distinct content types |

Rules:

* **Inferred facts do not count as self-authored.** A connector's guess
  ("Python (GitHub)") or an import's fact is reported beside the count, not
  in it: Domain 1 is what the user says about themselves.
* **The internal share event is not activity.** It mirrors a share, which
  Domain 5 already counts.
* **Blocked is not failed.** A connector the install cannot offer yet (no
  OAuth client, or not built: YouTube likes and Calendar wait on the user's
  Google setup) reads ``not_connected`` with the reason. An activity domain
  with no events and nothing connected is ``not_connected``, not a failure.
* **The voice floor is per script**, because a voice is learnt per language
  and Echo's language detection is script-based (romanised Hindi reads as
  Latin; `language_service`'s known gap). Met when any one script holds the
  floor in pieces or in words.
* **Centroid stability** is the bootstrap spread of the user's note vectors
  (stored in ``notes_global``, no model is loaded): the mean cosine distance
  between resampled centroids and the full one. Measured only once the floor
  is met; when the notes index is off on an install it is reported as not
  measurable and does not block.
* **The user-as-judge test (D-100) is not part of readiness.** It switches on
  "speak as me" per user; readiness reports whether the user can take it
  (enough live notes), not its result, which E-3.4 stores.

A criterion with a target of 0 is met: an operator disables it by setting
its threshold to 0.
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.activity_event import ActivityEvent
from app.models.note import Note
from app.models.personal_context import PersonalContext
from app.models.share import Share
from app.models.voice_signal import VoiceSignal

logger = logging.getLogger(__name__)

SELF_AUTHORED_SOURCE = "manual"
INTERNAL_CONNECTOR = "internal"


@dataclass
class Criterion:
    key: str
    label: str
    current: float
    target: float
    met: bool

    @property
    def fraction(self) -> float:
        if self.target <= 0:
            return 1.0
        return max(0.0, min(1.0, self.current / self.target))


@dataclass
class DomainReadiness:
    key: str  # facts | activity | signals | voice | shares
    domain: int  # the personal-brain.md domain number
    label: str
    # met | in_progress | not_started | not_connected
    status: str
    met: bool
    progress: float
    criteria: list[Criterion]
    summary: str
    missing: str | None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["criteria"] = [{**asdict(c), "fraction": round(c.fraction, 4)} for c in self.criteria]
        d["progress"] = round(self.progress, 4)
        return d


@dataclass
class Readiness:
    ready: bool
    progress: float
    domains: list[DomainReadiness]

    def to_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "progress": round(self.progress, 4), "domains": [d.to_dict() for d in self.domains]}


def _met(current: float, target: float) -> bool:
    return target <= 0 or current >= target


def _domain(key, domain, label, criteria, summary, missing, *, empty: bool, details=None, not_connected=False):
    met = all(c.met for c in criteria)
    progress = sum(c.fraction for c in criteria) / len(criteria) if criteria else 1.0
    if met:
        status = "met"
    elif not_connected:
        status = "not_connected"
    elif empty:
        status = "not_started"
    else:
        status = "in_progress"
    return DomainReadiness(
        key=key, domain=domain, label=label, status=status, met=met, progress=progress,
        criteria=criteria, summary=summary, missing=None if met else missing, details=details or {},
    )


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


# --------------------------------------------------------------------------- 1 facts

def _facts(db: Session, tenant_id: str) -> DomainReadiness:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    live = (PersonalContext.expires_at.is_(None)) | (PersonalContext.expires_at > now)
    rows = (
        db.query(PersonalContext.source, PersonalContext.kind)
        .filter(PersonalContext.user_id == tenant_id, live)
        .all()
    )
    own = [kind for source, kind in rows if source == SELF_AUTHORED_SOURCE]
    inferred = len(rows) - len(own)
    kinds = len(set(own))
    t_n, t_k = settings.ECHO_READY_FACTS_MIN, settings.ECHO_READY_FACT_KINDS_MIN
    criteria = [
        Criterion("facts", "Facts you wrote", len(own), t_n, _met(len(own), t_n)),
        Criterion("kinds", "Kinds of fact", kinds, t_k, _met(kinds, t_k)),
    ]
    summary = f"{_plural(len(own), 'fact')} you wrote, across {_plural(kinds, 'kind')}."
    if inferred:
        summary += f" {_plural(inferred, 'more fact')} Echo inferred {'is' if inferred == 1 else 'are'} kept but not counted."
    parts = []
    if len(own) < t_n:
        parts.append(f"write {_plural(t_n - len(own), 'more fact')} about yourself")
    if kinds < t_k:
        parts.append(f"cover {_plural(t_k - kinds, 'more kind')} (where you live, work, what you care about…)")
    missing = ("To finish: " + " and ".join(parts) + ".") if parts else None
    return _domain("facts", 1, "Facts about you", criteria, summary, missing, empty=not own,
                   details={"self_authored": len(own), "inferred": inferred})


# --------------------------------------------------------------------------- 2 activity

def _activity_sources(db: Session, tenant_id: str, by_connector: dict[str, int]) -> list[dict[str, Any]]:
    from app.connectors import registry
    from app.services import echo_connector_service

    registry.load_builtin()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for conn in registry.connectors():
        if not hasattr(conn, "consent_disclosure") or not hasattr(conn, "is_configured"):
            continue
        grant = echo_connector_service.get_grant(db, tenant_id, conn.name)
        if grant is not None:
            status, reason = "connected", None
        elif conn.is_configured():
            status, reason = "not_connected", None
        else:
            status, reason = "not_connected", "Not set up on this install yet."
        out.append({"name": conn.name, "label": conn.display_name, "kind": "connector", "status": status,
                    "available": conn.is_configured() or grant is not None, "reason": reason,
                    "events": by_connector.get(conn.name, 0)})
        seen.add(conn.name)
    for name, label, reason in echo_connector_service.PLANNED_CONNECTORS:
        if name in seen:
            continue
        out.append({"name": name, "label": label, "kind": "connector", "status": "not_connected",
                    "available": False, "reason": reason, "events": 0})
        seen.add(name)
    for name, n in sorted(by_connector.items()):
        if name not in seen:
            out.append({"name": name, "label": name.replace("_", " ").capitalize(), "kind": "import",
                        "status": "imported", "available": True, "reason": None, "events": n})
    return out


def _activity(db: Session, tenant_id: str) -> DomainReadiness:
    base = db.query(ActivityEvent).filter(
        ActivityEvent.tenant_id == tenant_id, ActivityEvent.connector != INTERNAL_CONNECTOR
    )
    count = base.count()
    first, last = (
        db.query(func.min(ActivityEvent.occurred_at), func.max(ActivityEvent.occurred_at))
        .filter(ActivityEvent.tenant_id == tenant_id, ActivityEvent.connector != INTERNAL_CONNECTOR)
        .one()
    )
    days = (last - first).days if first and last else 0
    by_connector = dict(
        db.query(ActivityEvent.connector, func.count(ActivityEvent.id))
        .filter(ActivityEvent.tenant_id == tenant_id, ActivityEvent.connector != INTERNAL_CONNECTOR)
        .group_by(ActivityEvent.connector)
        .all()
    )
    sources = _activity_sources(db, tenant_id, by_connector)
    t_n, t_d = settings.ECHO_READY_EVENTS_MIN, settings.ECHO_READY_EVENT_DAYS_MIN
    criteria = [
        Criterion("events", "Activity events", count, t_n, _met(count, t_n)),
        Criterion("days", "Days of history", days, t_d, _met(days, t_d)),
    ]
    connected = [s for s in sources if s["status"] in ("connected", "imported")]
    nothing_yet = count == 0 and not connected
    if count:
        summary = f"{_plural(count, 'event')} over {_plural(days, 'day')}, from {_plural(len([s for s in sources if s['events']]), 'source')}."
    else:
        summary = "No activity yet."
    parts = []
    if count < t_n:
        parts.append(f"{_plural(t_n - count, 'more event')}")
    if days < t_d:
        parts.append(f"history spanning {_plural(t_d - days, 'more day')}")
    if nothing_yet:
        missing = "Not connected yet: connect a service (GitHub) or import an export (Google Takeout, Spotify, Goodreads…) to start."
    else:
        missing = ("Needs " + " and ".join(parts) + ". Connect another service or import an export.") if parts else None
    def aware(dt):
        return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt

    return _domain("activity", 2, "What you do", criteria, summary, missing, empty=count == 0,
                   not_connected=nothing_yet,
                   details={"sources": sources, "first_at": aware(first), "last_at": aware(last)})


# --------------------------------------------------------------------------- 3 signals

def _signals(db: Session, tenant_id: str) -> DomainReadiness:
    rows = (
        db.query(VoiceSignal.signal_type)
        .filter(VoiceSignal.tenant_id == tenant_id, VoiceSignal.suppressed_at.is_(None))
        .all()
    )
    count = len(rows)
    types = len({r[0] for r in rows})
    t_n, t_k = settings.ECHO_READY_SIGNALS_MIN, settings.ECHO_READY_SIGNAL_TYPES_MIN
    criteria = [
        Criterion("signals", "Voice and personality signals", count, t_n, _met(count, t_n)),
        Criterion("types", "Kinds of signal", types, t_k, _met(types, t_k)),
    ]
    summary = f"{_plural(count, 'signal')} of {_plural(types, 'kind')} about how you write and think."
    parts = []
    if count < t_n:
        parts.append(f"{_plural(t_n - count, 'more signal')}")
    if types < t_k:
        parts.append(f"{_plural(t_k - types, 'more kind')}")
    missing = (
        "Needs " + " and ".join(parts) + ". Signals come from your notes and the things you mark as your own words."
        if parts else None
    )
    return _domain("signals", 3, "How you think", criteria, summary, missing, empty=count == 0,
                   details={"types": sorted({r[0] for r in rows})})


# --------------------------------------------------------------------------- 3 voice

def _own_writing(db: Session, tenant_id: str) -> list[tuple[str, str]]:
    """(kind, text) for every piece the user wrote: live notes and shares
    marked as their own words."""
    pieces: list[tuple[str, str]] = [
        ("note", body or "")
        for (body,) in db.query(Note.body_md).filter(Note.tenant_id == tenant_id, Note.deleted_at.is_(None))
    ]
    for text, annotation in db.query(Share.extracted_text, Share.user_annotation).filter(
        Share.tenant_id == tenant_id, Share.author_is_tenant.is_(True)
    ):
        body = text or annotation or ""
        if body.strip():
            pieces.append(("share", body))
    return pieces


def _script(text: str) -> str:
    from app.services import language_service

    return language_service.dominant_script(text) or "Other"


def _note_vectors(tenant_id: str) -> list[list[float]] | None:
    """The tenant's note vectors from ``notes_global``, or None when the
    index is off or unreachable. Never creates the collection."""
    if not settings.NOTES_INDEX_ENABLED:
        return None
    try:
        from app.services import chroma_service

        client = chroma_service.get_chroma_client()
        names = {c if isinstance(c, str) else c.name for c in client.list_collections()}
        if settings.CHROMA_NOTES_COLLECTION_NAME not in names:
            return []
        col = client.get_collection(settings.CHROMA_NOTES_COLLECTION_NAME)
        got = col.get(where={"tenant_id": tenant_id}, include=["embeddings"])
        embs = got.get("embeddings")
        return [list(map(float, e)) for e in (embs if embs is not None else [])]
    except Exception:
        logger.exception("echo readiness: could not read note vectors")
        return None


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _mean(vs: list[list[float]]) -> list[float]:
    dim = len(vs[0])
    return [sum(v[i] for v in vs) / len(vs) for i in range(dim)]


def bootstrap_spread(vectors: list[list[float]], resamples: int = 50, seed: int = 7) -> float:
    """Mean cosine distance between bootstrap-resampled centroids and the full
    centroid of ``vectors``: small means the voice has settled, so a few more
    notes would not move it. Deterministic (seeded)."""
    units = [_unit(v) for v in vectors]
    full = _unit(_mean(units))
    rng = random.Random(seed)
    total = 0.0
    for _ in range(resamples):
        sample = [units[rng.randrange(len(units))] for _ in range(len(units))]
        c = _unit(_mean(sample))
        total += 1.0 - sum(a * b for a, b in zip(c, full))
    return total / resamples


def _voice(db: Session, tenant_id: str) -> DomainReadiness:
    pieces = _own_writing(db, tenant_id)
    per_script: dict[str, dict[str, int]] = {}
    for _kind, text in pieces:
        s = _script(text)
        entry = per_script.setdefault(s, {"pieces": 0, "words": 0})
        entry["pieces"] += 1
        entry["words"] += len(text.split())
    t_p, t_w = settings.ECHO_READY_VOICE_PIECES_MIN, settings.ECHO_READY_VOICE_WORDS_MIN

    def score(e):  # how close a script is to the floor, by its better measure
        return max(e["pieces"] / t_p if t_p > 0 else 1.0, e["words"] / t_w if t_w > 0 else 1.0)

    best = max(per_script.items(), key=lambda kv: score(kv[1]), default=None)
    best_script, best_entry = best if best else (None, {"pieces": 0, "words": 0})
    floor_met = (t_p <= 0 and t_w <= 0) or (best is not None and (
        (t_p > 0 and best_entry["pieces"] >= t_p) or (t_w > 0 and best_entry["words"] >= t_w)
    ))
    floor_fraction = min(1.0, score(best_entry)) if best else (1.0 if t_p <= 0 and t_w <= 0 else 0.0)
    criteria = [Criterion("floor", "Your own writing, in one script", round(floor_fraction, 4), 1.0, floor_met)]

    stability: dict[str, Any] = {"measured": False, "spread": None, "max": settings.ECHO_READY_VOICE_SPREAD_MAX}
    if floor_met and settings.ECHO_READY_VOICE_SPREAD_MAX > 0:
        vectors = _note_vectors(tenant_id)
        if vectors is None:
            stability["reason"] = "The notes index is off on this install, so stability is not measured."
        elif len(vectors) < settings.ECHO_READY_VOICE_MIN_VECTORS:
            stability["reason"] = f"Needs at least {settings.ECHO_READY_VOICE_MIN_VECTORS} indexed notes to measure."
            criteria.append(Criterion("stability", "A settled voice", 0.0, 1.0, False))
        else:
            spread = bootstrap_spread(vectors)
            stable = spread <= settings.ECHO_READY_VOICE_SPREAD_MAX
            stability.update({"measured": True, "spread": round(spread, 5), "vectors": len(vectors)})
            criteria.append(Criterion("stability", "A settled voice", 1.0 if stable else 0.0, 1.0, stable))

    notes_live = sum(1 for k, _ in pieces if k == "note")
    test_min = settings.ECHO_VOICE_TEST_NOTES_MIN
    voice_test = {"eligible": notes_live >= test_min, "notes": notes_live, "notes_needed": max(0, test_min - notes_live)}

    if best:
        label = f"{best_script} script"
        summary = f"{_plural(best_entry['pieces'], 'piece')} of your own writing in {label} ({_plural(best_entry['words'], 'word')})."
        others = len(per_script) - 1
        if others > 0:
            summary += f" Plus writing in {_plural(others, 'other script')}."
    else:
        summary = "Nothing you wrote yourself yet."
    if not floor_met:
        need_p = max(0, t_p - best_entry["pieces"]) if t_p > 0 else None
        need_w = max(0, t_w - best_entry["words"]) if t_w > 0 else None
        opts = [x for x in (need_p and _plural(need_p, "more note"), need_w and _plural(need_w, "more word")) if x]
        missing = f"Write {' or '.join(opts)} in one language: notes on your sources, or things you share and mark as your own words."
    elif not all(c.met for c in criteria):
        missing = "Your voice is still shifting as you write; a few more notes will settle it."
    else:
        missing = None
    return _domain("voice", 3, "How you write", criteria, summary, missing, empty=not pieces,
                   details={"per_script": per_script, "best_script": best_script, "stability": stability,
                            "voice_test": voice_test})


# --------------------------------------------------------------------------- 5 shares

def _shares(db: Session, tenant_id: str) -> DomainReadiness:
    rows = (
        db.query(Share.content_type, func.count(Share.id))
        .filter(Share.tenant_id == tenant_id)
        .group_by(Share.content_type)
        .all()
    )
    count = sum(n for _, n in rows)
    types = len(rows)
    t_n, t_k = settings.ECHO_READY_SHARES_MIN, settings.ECHO_READY_SHARE_TYPES_MIN
    criteria = [
        Criterion("shares", "Things you shared", count, t_n, _met(count, t_n)),
        Criterion("types", "Kinds of thing", types, t_k, _met(types, t_k)),
    ]
    summary = f"{_plural(count, 'share')} of {_plural(types, 'kind')}."
    parts = []
    if count < t_n:
        parts.append(f"{_plural(t_n - count, 'more share')}")
    if types < t_k:
        parts.append(f"{_plural(t_k - types, 'more kind')} (links, quotes, images, chats…)")
    missing = ("Needs " + " and ".join(parts) + ".") if parts else None
    return _domain("shares", 5, "What you share", criteria, summary, missing, empty=count == 0,
                   details={"content_types": {ct: n for ct, n in rows}})


# --------------------------------------------------------------------------- the gate

def evaluate(db: Session, tenant_id: str) -> Readiness:
    domains = [_facts(db, tenant_id), _activity(db, tenant_id), _signals(db, tenant_id),
               _voice(db, tenant_id), _shares(db, tenant_id)]
    return Readiness(
        ready=all(d.met for d in domains),
        progress=sum(d.progress for d in domains) / len(domains),
        domains=domains,
    )
