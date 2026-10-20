"""``/echo/draft`` and ``/echo/drafts``: "speak as me" (S-3.4.1 / E-3.4).

Every route needs ``echo_speak_as_me`` (Studio); a tier without it is a 403.
Beyond the tier, a draft needs the install switch, readiness and the user's
own passed voice test (D-100), and fits under a daily cap; ``GET
/echo/draft/status`` says which of those is missing, in words. Drafts are
never sent.

Contract agreed with the Echo bubble (S-3.8.1), which hosts this endpoint.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.user import User
from app.services import echo_draft_service as drafts
from app.services.tier_service import require_feature

router = APIRouter(prefix="/echo", tags=["echo"])

SPEAK = require_feature("echo_speak_as_me")


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    message: str = Field(min_length=1, max_length=8000)
    audience: str | None = Field(default=None, max_length=200)
    # `register` is the wire name; pydantic's BaseModel already has one.
    register_: Literal["intimate", "casual", "professional", "public"] | None = Field(default=None, alias="register")
    language: Literal["en", "hi-Deva", "hi-Latn", "mixed"] | None = None
    acknowledge_names: list[str] = Field(default_factory=list, max_length=20)


def _blocked(code: str, message: str, status: drafts.DraftStatus) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message, "status": status.to_dict()})


@router.get("/draft/status")
def draft_status(db: Session = Depends(get_db), current_user: User = Depends(SPEAK)):
    return drafts.status(db, current_user).to_dict()


@router.post("/draft", status_code=201)
def create_draft(body: DraftRequest, db: Session = Depends(get_db), current_user: User = Depends(SPEAK)):
    try:
        row = drafts.draft(
            db, current_user, body.message.strip(),
            audience=(body.audience or "").strip() or None,
            register=body.register_,
            language=body.language,
            acknowledge_names=body.acknowledge_names,
        )
    except drafts.DraftBlocked as e:
        raise _blocked(e.code, e.message, e.status)
    except drafts.DraftCapReached as e:
        raise HTTPException(status_code=429, detail={"code": "daily_cap", "message": e.message})
    except drafts.NamesNeedConfirmation as e:
        raise HTTPException(status_code=409, detail={
            "code": "names_need_confirmation",
            "names": e.names,
            "message": (
                "This message names someone who looks like a private person: "
                + ", ".join(e.names)
                + ". Echo will not add anything about them beyond what the message says. Confirm to draft."
            ),
        })
    return drafts.to_dict(row)


@router.get("/drafts")
def list_drafts(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), current_user: User = Depends(SPEAK)):
    return {"items": [drafts.to_dict(r) for r in drafts.list_drafts(db, current_user.id, limit)]}


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: str, db: Session = Depends(get_db), current_user: User = Depends(SPEAK)):
    try:
        return drafts.to_dict(drafts.get_draft(db, current_user.id, draft_id))
    except drafts.DraftNotFound:
        raise HTTPException(status_code=404, detail="Draft not found")


@router.delete("/drafts/{draft_id}", status_code=204)
def delete_draft(draft_id: str, db: Session = Depends(get_db), current_user: User = Depends(SPEAK)):
    try:
        drafts.delete_draft(db, current_user.id, draft_id)
    except drafts.DraftNotFound:
        raise HTTPException(status_code=404, detail="Draft not found")
