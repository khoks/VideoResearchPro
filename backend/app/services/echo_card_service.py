"""Anticipation cards in the Echo panel (S-3.8.2).

A card offers one next step the user may want: a saved search whose answer
changed, shares read since the user last opened the inbox, or questions for
the page in view. The frequency cap and the dismissal rule below were
pre-registered before any card was built
(docs/notes/2026-10-20-anticipation-cards-preregistration.md); changing a
number needs a new note and a decision entry.

Cards are computed when the panel asks for them, and only then: nothing
here pushes, badges or notifies. State lives in ``echo_card_state``
(``app/models/echo_card_state.py``), one row per (tenant, key).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.echo_card_state import EchoCardState
from app.models.notification import Notification
from app.models.share import Share
from app.services import notification_service

# --- Pre-registered (2026-10-20) -------------------------------------------
KINDS = ("saved_search", "shares", "questions")  # also the display order
MAX_CARDS = 3  # per panel view, one per kind
MAX_DAYS = 3  # distinct UTC days a key may be shown
MUTE_AFTER = 3  # dismissals of one kind...
MUTE_WINDOW = timedelta(days=30)  # ...within this window turn the kind off
# ---------------------------------------------------------------------------

#: When the inbox has never been opened, shares read this recently count.
SHARES_LOOKBACK = timedelta(days=14)
MUTE_PREFIX = "mute:"
SEEN_SHARES = "seen:shares"
_CONTEXT_RE = re.compile(r"^(library|job:[\w-]{1,64}|document:[\w:-]{1,100})$")
_KEY_RE = re.compile(r"^(saved_search|shares|questions):[\w:-]{1,180}$")


class CardError(ValueError):
    pass


@dataclass
class Card:
    key: str
    kind: str
    title: str
    body: str | None = None
    href: str | None = None
    action_label: str | None = None
    #: For a questions card: the suggestions context the panel fetches.
    context: str | None = None


@dataclass
class CardsResult:
    cards: list[Card]
    muted_kinds: list[str]
    #: Said once, right after the dismissal rule turned a kind off.
    notice: str | None = None
    notice_kind: str | None = None

    def as_dict(self) -> dict:
        return {
            "cards": [asdict(c) for c in self.cards],
            "muted_kinds": self.muted_kinds,
            "notice": self.notice,
            "notice_kind": self.notice_kind,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _rows(db: Session, tenant_id: str, keys: list[str]) -> dict[str, EchoCardState]:
    if not keys:
        return {}
    return {
        r.key: r
        for r in db.query(EchoCardState).filter(EchoCardState.tenant_id == tenant_id, EchoCardState.key.in_(keys))
    }


def _row(db: Session, tenant_id: str, key: str, kind: str) -> EchoCardState:
    row = db.query(EchoCardState).filter(EchoCardState.tenant_id == tenant_id, EchoCardState.key == key).first()
    if row is None:
        row = EchoCardState(tenant_id=tenant_id, key=key, kind=kind, shown_days=0)
        db.add(row)
    return row


def kind_of(key: str) -> str:
    if not _KEY_RE.fullmatch(key or ""):
        raise CardError("not a card key")
    return key.split(":", 1)[0]


def check_context(context: str | None) -> str | None:
    if context is None or context == "":
        return None
    if not _CONTEXT_RE.fullmatch(context):
        raise CardError("context must be library, job:<id> or document:<id>")
    return context


def muted_kinds(db: Session, tenant_id: str) -> list[str]:
    rows = _rows(db, tenant_id, [MUTE_PREFIX + k for k in KINDS])
    return [k for k in KINDS if (r := rows.get(MUTE_PREFIX + k)) is not None and r.dismissed_at is not None]


def _showable(row: EchoCardState | None, today: date) -> bool:
    if row is None:
        return True
    if row.dismissed_at is not None or row.acted_at is not None:
        return False
    # Today already counted as one of the days: showing it again is free.
    return row.shown_days < MAX_DAYS or row.last_shown_on == today


# --- Candidates -------------------------------------------------------------


def _saved_search_candidates(db: Session, tenant_id: str) -> list[Card]:
    rows = (
        db.query(Notification)
        .filter(
            Notification.tenant_id == tenant_id,
            Notification.kind == notification_service.KIND_SAVED_SEARCH_CHANGED,
            Notification.read_at.is_(None),
        )
        .order_by(Notification.created_at.desc())
        .limit(20)
        .all()
    )
    return [
        Card(
            key=f"saved_search:{n.id}",
            kind="saved_search",
            title=n.title,
            body=n.body,
            href=n.href,
            action_label="See what changed",
        )
        for n in rows
    ]


def _shares_candidate(db: Session, tenant_id: str) -> list[Card]:
    seen = _rows(db, tenant_id, [SEEN_SHARES]).get(SEEN_SHARES)
    since = seen.acted_at if seen is not None and seen.acted_at is not None else _now() - SHARES_LOOKBACK
    rows = (
        db.query(Share.id, Share.processing_state, Share.updated_at)
        .filter(
            Share.tenant_id == tenant_id,
            # Direct shares only: an import can be 100k rows, and the user
            # watched it happen.
            Share.import_id.is_(None),
            Share.processing_state.in_(("processed", "failed")),
            Share.updated_at > since,
        )
        .order_by(Share.updated_at.desc())
        .limit(500)
        .all()
    )
    if not rows:
        return []
    read = sum(1 for r in rows if r.processing_state == "processed")
    failed = len(rows) - read
    parts = []
    if read:
        parts.append(f"{read} {'share was' if read == 1 else 'shares were'} read")
    if failed:
        parts.append(f"{failed} {'needs' if failed == 1 else 'need'} a retry")
    return [
        Card(
            key=f"shares:{rows[0].id}",
            kind="shares",
            title="New in your shares inbox",
            body=" and ".join(parts) + " since you last looked.",
            href="/echo/inbox",
            action_label="Open the inbox",
        )
    ]


def _questions_candidate(context: str | None) -> list[Card]:
    if context is None:
        return []
    return [Card(key=f"questions:{context}", kind="questions", title="You might ask", context=context)]


# --- The rules --------------------------------------------------------------


def cards_for(db: Session, tenant_id: str, context: str | None = None) -> CardsResult:
    """The cards for one panel view, after the cap, the dismissals and the
    muted kinds; records the view (once per key per day)."""
    context = check_context(context)
    today = _today()
    muted = muted_kinds(db, tenant_id)
    candidates: dict[str, list[Card]] = {
        "saved_search": _saved_search_candidates(db, tenant_id) if "saved_search" not in muted else [],
        "shares": _shares_candidate(db, tenant_id) if "shares" not in muted else [],
        "questions": _questions_candidate(context) if "questions" not in muted else [],
    }
    states = _rows(db, tenant_id, [c.key for cards in candidates.values() for c in cards])
    chosen: list[Card] = []
    for kind in KINDS:
        card = next((c for c in candidates[kind] if _showable(states.get(c.key), today)), None)
        if card is not None:
            chosen.append(card)
        if len(chosen) == MAX_CARDS:
            break

    for card in chosen:
        # A questions card has no content until the panel fetches the
        # suggestions, and an empty one is not rendered: the panel reports
        # it shown (``record_shown``) only when a question appears, or the
        # pre-registered act rate would count views nobody saw.
        if card.kind != "questions":
            _count_view(states.get(card.key) or _row(db, tenant_id, card.key, card.kind), today)

    notice = notice_kind = None
    for kind in muted:
        row = _row(db, tenant_id, MUTE_PREFIX + kind, kind)
        if row.acted_at is None:  # muted by the rule and not said yet
            row.acted_at = _now()
            notice = f"You dismissed {MUTE_AFTER} of these, so {_KIND_NAME[kind]} cards are off. You can turn them back on."
            notice_kind = kind
    db.commit()
    return CardsResult(cards=chosen, muted_kinds=muted, notice=notice, notice_kind=notice_kind)


_KIND_NAME = {"saved_search": "saved-search", "shares": "shares-inbox", "questions": "question"}


def _count_view(row: EchoCardState, today: date) -> None:
    if row.last_shown_on != today:
        row.shown_days = (row.shown_days or 0) + 1
        row.last_shown_on = today


def record_shown(db: Session, tenant_id: str, key: str) -> None:
    """The panel rendered this card (a questions card with at least one
    question). Counted once per day, like every view."""
    kind = kind_of(key)
    _count_view(_row(db, tenant_id, key, kind), _today())
    db.commit()


def dismiss(db: Session, tenant_id: str, key: str) -> str | None:
    """× on a card: its key never shows again. Returns the kind if this
    dismissal turned the kind off (three within 30 days)."""
    kind = kind_of(key)
    now = _now()
    row = _row(db, tenant_id, key, kind)
    if row.dismissed_at is None:
        row.dismissed_at = now
    db.flush()
    mute = _rows(db, tenant_id, [MUTE_PREFIX + kind]).get(MUTE_PREFIX + kind)
    if mute is not None and mute.dismissed_at is not None:
        db.commit()
        return None
    floor = now - MUTE_WINDOW
    if mute is not None and mute.updated_at and mute.updated_at > floor:
        floor = mute.updated_at  # turned back on: count from then
    recent = (
        db.query(EchoCardState)
        .filter(
            EchoCardState.tenant_id == tenant_id,
            EchoCardState.kind == kind,
            EchoCardState.key.like(f"{kind}:%"),
            EchoCardState.dismissed_at.is_not(None),
            EchoCardState.dismissed_at >= floor,
        )
        .count()
    )
    if recent < MUTE_AFTER:
        db.commit()
        return None
    mute = mute or _row(db, tenant_id, MUTE_PREFIX + kind, kind)
    mute.dismissed_at = now
    mute.acted_at = None  # the panel says so once
    db.commit()
    return kind


def act(db: Session, tenant_id: str, key: str) -> None:
    """The user followed a card: retire its key (not a dismissal). A
    saved-search card's notice is read now."""
    kind = kind_of(key)
    row = _row(db, tenant_id, key, kind)
    if row.acted_at is None:
        row.acted_at = _now()
    db.commit()
    if kind == "saved_search":
        notification_service.mark_read(db, tenant_id, key.split(":", 1)[1])


def settings(db: Session, tenant_id: str) -> dict[str, bool]:
    muted = set(muted_kinds(db, tenant_id))
    return {k: k not in muted for k in KINDS}


def set_settings(db: Session, tenant_id: str, enabled: dict[str, bool]) -> dict[str, bool]:
    """Turn kinds on or off directly. Turning one back on restarts its
    dismissal count."""
    now = _now()
    for kind, on in enabled.items():
        if kind not in KINDS:
            raise CardError(f"unknown card kind {kind!r}")
        row = _row(db, tenant_id, MUTE_PREFIX + kind, kind)
        if on:
            row.dismissed_at = None
            row.updated_at = now
        elif row.dismissed_at is None:
            row.dismissed_at = now
            row.acted_at = now  # the user did it: nothing to announce
    db.commit()
    return settings(db, tenant_id)


def mark_shares_seen(db: Session, tenant_id: str) -> None:
    """The user opened the shares inbox: what is there now is not news."""
    row = _row(db, tenant_id, SEEN_SHARES, "shares")
    row.acted_at = _now()
    db.commit()
