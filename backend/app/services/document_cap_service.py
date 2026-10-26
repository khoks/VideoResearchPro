"""The per-tenant document cap — T-5.2.10 / D-111.

``TIER_CAPABILITIES[tier]["document_count_cap"]`` (Free 500, Pro 5,000,
Studio unlimited) is advertised on the pricing page. This module enforces it.

**What counts.** The documents a tenant can SEE: their rows in
``document_visibility`` (D-063). ``documents`` is a shared, deduplicated
cache, so the cap is on the tenant's catalogue, not on rows they created —
a dedup hit on a document the tenant already sees adds nothing and never
counts, while a dedup hit on one only someone else had ingested is new to
this tenant and does.

**Where it is checked.** Before ingest, at each entry point, so a refusal
never throws away finished work:

* job approval (``PUT /jobs/{id}/approve``) — the approved documents the
  tenant cannot already see;
* PDF upload and pasted URLs (``/library/upload-pdf``, ``/library/paste-urls``);
* channel subscribe and sync, and subscription jobs created through
  ``POST /jobs`` — refused outright when the library is already full;
* the subscription task itself (``execute_subscription_job``), which is
  where a sync with no request behind it (a scheduled one) meets the cap:
  it stops at the cap instead of refusing (``SyncBudget``).

**The rule.** A request that names what it adds (an approval, a paste batch,
an upload) is all or nothing: when it does not fit, nothing is added and the
refusal says how much room is left, so the user chooses what to drop. A sync
names nothing in advance, so it takes uploads in playlist order (newest
first) until the cap and records how many it left out.

A tenant already over the cap (a downgrade, or documents added before this
check existed) keeps everything; they just cannot add more.

``visibility_service.grant`` deliberately has no backstop: by the time it
runs the work is done, and refusing a grant there would hide finished work.

Refusals are ``QuotaExceededError`` (HTTP 429), the shape every other quota
uses (D-045), with ``resource="documents"`` and a ``message`` to show as is.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.user import User
from app.services.quota_metering_service import QuotaExceededError
from app.services.tier_service import get_user_tier, quota_limit

logger = logging.getLogger(__name__)

RESOURCE = "documents"
CAP_KEY = "document_count_cap"

# Actions name the entry point, which picks the advice in the message.
ACTION_APPROVE = "approve"
ACTION_PASTE = "paste"
ACTION_UPLOAD = "upload"
ACTION_SYNC = "sync"

# SQLite caps bound parameters per statement; keep IN lists well under it.
_IN_CHUNK = 500


def _chunks(items: list[str], size: int = _IN_CHUNK):
    for i in range(0, len(items), size):
        yield items[i : i + size]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def cap_for(user: User) -> int:
    """The user's cap; ``-1`` means unlimited."""
    return int(quota_limit(user, CAP_KEY))


def visible_count(db: Session, tenant_id: str) -> int:
    """How many documents ``tenant_id`` can see — what the cap counts."""
    return int(
        db.query(func.count(DocumentVisibility.id))
        .filter(DocumentVisibility.tenant_id == tenant_id)
        .scalar()
        or 0
    )


def not_yet_visible(db: Session, tenant_id: str, document_ids: Iterable[str]) -> list[str]:
    """The ids in ``document_ids`` that ``tenant_id`` cannot see yet, deduplicated."""
    ids = [d for d in dict.fromkeys(document_ids) if d]
    if not ids:
        return []
    seen: set[str] = set()
    for chunk in _chunks(ids):
        seen.update(
            row[0]
            for row in db.query(DocumentVisibility.document_id).filter(
                DocumentVisibility.tenant_id == tenant_id,
                DocumentVisibility.document_id.in_(chunk),
            )
        )
    return [d for d in ids if d not in seen]


def headroom(db: Session, user: User) -> int | None:
    """Documents the user may still add; ``None`` when the plan has no cap."""
    cap = cap_for(user)
    if cap < 0:
        return None
    return max(0, cap - visible_count(db, user.id))


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def _plan_name(user: User) -> str:
    return get_user_tier(user).value.capitalize()


def refusal_message(
    action: str, plan: str, consumed: int, limit: int, requested: int | None
) -> str:
    """The sentence the user sees. Plain numbers, what to do next."""
    available = max(0, limit - consumed)
    if consumed > limit:
        state = (
            f"Your library holds {consumed:,} documents, over the {plan} plan's "
            f"cap of {limit:,}."
        )
    elif available == 0:
        state = f"Your library is at the {plan} plan's cap of {limit:,} documents."
    else:
        state = (
            f"Your library holds {consumed:,} of the {limit:,} documents the {plan} "
            f"plan allows, so there is room for {available:,} more."
        )

    noun = {ACTION_APPROVE: "approval", ACTION_PASTE: "batch", ACTION_UPLOAD: "upload"}.get(action)
    adds = ""
    if requested is not None and noun is not None:
        if action == ACTION_UPLOAD:
            adds = " This PDF is not in your library yet."
        else:
            adds = (
                f" This {noun} would add {requested:,} "
                f"{'document' if requested == 1 else 'documents'} you do not have yet."
            )

    higher = "move to a plan with a higher cap"
    if action == ACTION_APPROVE and available > 0 and requested is not None:
        advice = f" Deselect at least {requested - available:,}, or {higher}."
    elif action == ACTION_APPROVE:
        advice = f" Approve only sources already in your library, or {higher}."
    elif action == ACTION_PASTE and available > 0:
        advice = f" Paste at most {available:,} new links at a time, or {higher}."
    elif action == ACTION_SYNC:
        advice = f" A sync cannot add anything new until you {higher}."
    else:
        advice = f" Nothing new can be added until you {higher}."
    keep = " Documents already in your library stay." if available == 0 else ""
    return f"{state}{adds}{advice}{keep}"


class DocumentCapExceeded(QuotaExceededError):
    """HTTP 429 in the shared quota shape, plus what the UI needs to say why.

    ``detail`` keeps every ``QuotaExceededError`` key (``error``,
    ``resource``, ``consumed``, ``limit``, ``retry_at`` — None, the cap is
    not periodic) and adds ``requested`` (documents the action would add, or
    None for a sync, which cannot know), ``available`` and ``message``.
    """

    def __init__(
        self, *, action: str, plan: str, consumed: int, limit: int, requested: int | None
    ) -> None:
        super().__init__(resource=RESOURCE, consumed=consumed, limit=limit, retry_at=None)
        self.detail = {
            **self.detail,
            "requested": requested,
            "available": max(0, limit - consumed),
            "message": refusal_message(action, plan, consumed, limit, requested),
        }


def enforce(
    db: Session,
    user: User,
    *,
    action: str,
    document_ids: Iterable[str] = (),
    unseen: int = 0,
) -> int:
    """Refuse (429) when the action would take ``user`` past the cap.

    ``document_ids`` are existing documents the action would grant; the ones
    the user already sees are dedup hits and do not count. ``unseen`` counts
    documents not in the shared library at all, which are new by definition.
    Returns how many new documents the action adds; on a plan with no cap it
    returns 0 without querying.
    """
    cap = cap_for(user)
    if cap < 0:
        return 0
    new = len(not_yet_visible(db, user.id, document_ids)) + max(0, unseen)
    if new == 0:
        return 0
    consumed = visible_count(db, user.id)
    if consumed + new <= cap:
        return new
    logger.info(
        "document cap: refused %s for user %s (%d visible + %d new > cap %d)",
        action, user.id[:8], consumed, new, cap,
    )
    raise DocumentCapExceeded(
        action=action, plan=_plan_name(user), consumed=consumed, limit=cap, requested=new
    )


def refuse_if_full(db: Session, user: User, *, action: str = ACTION_SYNC) -> None:
    """Refuse (429) an action whose additions are unknown up front (a sync)
    when the library has no room left at all."""
    cap = cap_for(user)
    if cap < 0:
        return
    consumed = visible_count(db, user.id)
    if consumed < cap:
        return
    logger.info(
        "document cap: refused %s for user %s (%d visible, cap %d)",
        action, user.id[:8], consumed, cap,
    )
    raise DocumentCapExceeded(
        action=action, plan=_plan_name(user), consumed=consumed, limit=cap, requested=None
    )


# ---------------------------------------------------------------------------
# Syncs: stop at the cap
# ---------------------------------------------------------------------------


@dataclass
class SyncBudget:
    """How many NEW documents a subscription sync may still link.

    ``remaining`` is ``None`` when there is no cap (Studio, or a job with no
    tenant). ``admit`` is called once per channel with that channel's
    unlinked uploads, in playlist order; it keeps every upload the tenant
    already sees, then new ones while room remains, and counts the rest.
    """

    tenant_id: str | None
    remaining: int | None
    limit: int = -1
    plan: str = ""
    skipped: int = 0

    def admit(self, db: Session, video_ids: list[str]) -> list[str]:
        if self.remaining is None or not video_ids or not self.tenant_id:
            return list(video_ids)
        visible: set[str] = set()
        for chunk in _chunks(list(dict.fromkeys(video_ids))):
            visible.update(
                row[0]
                for row in db.query(Document.video_id)
                .join(DocumentVisibility, DocumentVisibility.document_id == Document.document_id)
                .filter(
                    DocumentVisibility.tenant_id == self.tenant_id,
                    Document.video_id.in_(chunk),
                )
            )
        kept: list[str] = []
        for vid in dict.fromkeys(video_ids):  # a repeated id is one document
            if vid in visible:
                kept.append(vid)
            elif self.remaining > 0:
                kept.append(vid)
                self.remaining -= 1
            else:
                self.skipped += 1
        return kept

    def note(self) -> str | None:
        """What the job says when the cap left uploads out; None otherwise."""
        if not self.skipped:
            return None
        n = self.skipped
        return (
            f"{n:,} new {'upload was' if n == 1 else 'uploads were'} left out: "
            f"your library reached the {self.plan} plan's cap of {self.limit:,} documents."
        )


def sync_budget(db: Session, tenant_id: str | None) -> SyncBudget:
    """The budget for one subscription sync run by ``tenant_id``.

    A job with no tenant (legacy rows) or whose account no longer exists has
    no plan to read, so it is not capped.
    """
    if not tenant_id:
        return SyncBudget(tenant_id=None, remaining=None)
    user = db.get(User, tenant_id)
    if user is None:
        logger.debug("document cap: no account for tenant %s; sync not capped", tenant_id[:8])
        return SyncBudget(tenant_id=tenant_id, remaining=None)
    cap = cap_for(user)
    if cap < 0:
        return SyncBudget(tenant_id=tenant_id, remaining=None)
    return SyncBudget(
        tenant_id=tenant_id,
        remaining=max(0, cap - visible_count(db, tenant_id)),
        limit=cap,
        plan=_plan_name(user),
    )
