"""``/echo/voice-test``: the "which of these did you write?" test, in the app (T-3.4.1.8).

The test that switches "speak as me" on per user (D-100, D-102), which an
operator used to run with ``scripts/voice_match_harness.py``. The work is in
``echo_voice_test_service``, shared with that script.

Every route needs ``echo_speak_as_me`` (Studio); a tier without it is a 403.
Every test is the caller's own: another user's test id is a 404.

- ``GET /echo/voice-test``: whether a test can start (each reason it cannot,
  in words), what one costs, the user's gate, and their newest test.
- ``POST /echo/voice-test``: start one (202). Only this call spends: about
  40 draft-model calls, written in the background.
- ``GET /echo/voice-test/{id}``: the test, for polling while it is written.
- ``PUT /echo/voice-test/{id}/picks``: the user's pick for one pair.
- ``POST /echo/voice-test/{id}/score``: score it and store the gate.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.user import User
from app.services import echo_draft_service
from app.services import echo_voice_test_service as voice_test
from app.services.tier_service import require_feature

router = APIRouter(prefix="/echo", tags=["echo"])

SPEAK = require_feature("echo_speak_as_me")


class PickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair: str = Field(pattern=r"^p\d{2,3}$")
    pick: Literal["A", "B"]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Voice test not found")


def _conflict(e: voice_test.VoiceTestBlocked) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": e.code, "message": e.message})


@router.get("/voice-test")
def voice_test_overview(db: Session = Depends(get_db), current_user: User = Depends(SPEAK)):
    return voice_test.overview(db, current_user)


@router.post("/voice-test", status_code=202)
def start_voice_test(db: Session = Depends(get_db), current_user: User = Depends(SPEAK)):
    try:
        row = voice_test.start(db, current_user)
    except voice_test.VoiceTestBlocked as e:
        raise _conflict(e)
    return voice_test.to_dict(row)


@router.get("/voice-test/{test_id}")
def get_voice_test(test_id: str, db: Session = Depends(get_db), current_user: User = Depends(SPEAK)):
    try:
        return voice_test.to_dict(voice_test.get_test(db, current_user.id, test_id))
    except voice_test.VoiceTestNotFound:
        raise _not_found()


@router.put("/voice-test/{test_id}/picks")
def pick_voice_test(test_id: str, body: PickRequest, db: Session = Depends(get_db), current_user: User = Depends(SPEAK)):
    try:
        row = voice_test.pick(db, current_user.id, test_id, body.pair, body.pick)
    except voice_test.VoiceTestNotFound:
        raise _not_found()
    except voice_test.VoiceTestConflict as e:
        raise _conflict(e)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return voice_test.to_dict(row)


@router.post("/voice-test/{test_id}/score")
def score_voice_test(test_id: str, db: Session = Depends(get_db), current_user: User = Depends(SPEAK)):
    try:
        row = voice_test.score(db, current_user, test_id)
    except voice_test.VoiceTestNotFound:
        raise _not_found()
    except voice_test.VoiceTestConflict as e:
        raise _conflict(e)
    return {"test": voice_test.to_dict(row), "gate": echo_draft_service.voice_gate(db, current_user.id)}
