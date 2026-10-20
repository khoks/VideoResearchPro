"""``/echo/cards``: anticipation cards in the Echo panel (S-3.8.2 / E-3.8).

The cards are read only when the panel opens; nothing here notifies. The
frequency cap and the dismissal rule are pre-registered
(docs/notes/2026-10-20-anticipation-cards-preregistration.md) and live in
``echo_card_service``. A separate router so this work does not collide with
``routers/echo.py``. Every route acts on the caller's own cards and needs the
``echo_personal_brain`` feature, like the rest of ``/echo``.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.user import User
from app.services import echo_card_service as cards
from app.services.tier_service import require_feature

router = APIRouter(prefix="/echo/cards", tags=["echo"])

ECHO = require_feature("echo_personal_brain")


class CardItem(BaseModel):
    key: str
    kind: str
    title: str
    body: str | None = None
    href: str | None = None
    action_label: str | None = None
    context: str | None = None


class CardsResponse(BaseModel):
    cards: list[CardItem]
    muted_kinds: list[str]
    notice: str | None = None
    notice_kind: str | None = None


class DismissResponse(BaseModel):
    #: The kind this dismissal turned off, if it was the third in 30 days.
    muted_kind: str | None = None


class CardSettings(BaseModel):
    kinds: dict[str, bool]


def _bad(exc: cards.CardError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get("", response_model=CardsResponse)
def list_cards(
    context: str | None = Query(None, max_length=120, description="library, job:<id> or document:<id>"),
    current_user: User = Depends(ECHO),
    db: Session = Depends(get_db),
) -> CardsResponse:
    try:
        result = cards.cards_for(db, current_user.id, context)
    except cards.CardError as exc:
        raise _bad(exc)
    return CardsResponse(**result.as_dict())


@router.post("/dismiss", response_model=DismissResponse)
def dismiss_card(
    key: str = Query(..., max_length=200),
    current_user: User = Depends(ECHO),
    db: Session = Depends(get_db),
) -> DismissResponse:
    try:
        return DismissResponse(muted_kind=cards.dismiss(db, current_user.id, key))
    except cards.CardError as exc:
        raise _bad(exc)


@router.post("/shown", status_code=204)
def card_shown(
    key: str = Query(..., max_length=200),
    current_user: User = Depends(ECHO),
    db: Session = Depends(get_db),
) -> Response:
    """A questions card was rendered with at least one question."""
    try:
        cards.record_shown(db, current_user.id, key)
    except cards.CardError as exc:
        raise _bad(exc)
    return Response(status_code=204)


@router.post("/act", status_code=204)
def act_on_card(
    key: str = Query(..., max_length=200),
    current_user: User = Depends(ECHO),
    db: Session = Depends(get_db),
) -> Response:
    try:
        cards.act(db, current_user.id, key)
    except cards.CardError as exc:
        raise _bad(exc)
    return Response(status_code=204)


@router.get("/settings", response_model=CardSettings)
def get_card_settings(current_user: User = Depends(ECHO), db: Session = Depends(get_db)) -> CardSettings:
    return CardSettings(kinds=cards.settings(db, current_user.id))


@router.put("/settings", response_model=CardSettings)
def put_card_settings(
    body: CardSettings,
    current_user: User = Depends(ECHO),
    db: Session = Depends(get_db),
) -> CardSettings:
    try:
        return CardSettings(kinds=cards.set_settings(db, current_user.id, body.kinds))
    except cards.CardError as exc:
        raise _bad(exc)


@router.post("/seen/shares", status_code=204)
def shares_seen(current_user: User = Depends(ECHO), db: Session = Depends(get_db)) -> Response:
    """The shares inbox calls this when it opens."""
    cards.mark_shares_seen(db, current_user.id)
    return Response(status_code=204)
