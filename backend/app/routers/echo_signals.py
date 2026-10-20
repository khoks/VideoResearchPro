"""``/echo/signals``: the signals panel (S-3.3.1 / E-3.3).

Every route acts on the caller's own signals and needs the
``echo_personal_brain`` feature, like the rest of ``/echo``. A separate
router so the signals work does not collide with the intake and connector
work in ``routers/echo.py``. DELETE is a tombstone, not a delete: the row
stays so extraction can see the user rejected it (the brain delete,
``DELETE /echo/brain``, removes it for good).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.user import User
from app.config import settings
from app.schemas.voice_signal import (
    LearningState,
    LearnResponse,
    VoiceSignalCreate,
    VoiceSignalItem,
    VoiceSignalList,
    VoiceSignalPatch,
)
from app.services import echo_signal_extraction as extraction
from app.services import echo_signal_service as signals
from app.services.tier_service import require_feature

router = APIRouter(prefix="/echo/signals", tags=["echo"])

ECHO = require_feature("echo_personal_brain")


def _item(row) -> VoiceSignalItem:
    d = signals.to_dict(row)
    d["register_"] = d.pop("register")
    return VoiceSignalItem(**{k: v for k, v in d.items() if k in VoiceSignalItem.model_fields})


@router.get("", response_model=VoiceSignalList)
def list_signals(
    signal_type: str | None = Query(default=None),
    language: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(ECHO),
):
    rows = signals.list_signals(db, current_user.id, signal_type=signal_type, language=language)
    return VoiceSignalList(
        items=[_item(r) for r in rows],
        consent_version=signals.CONSENT_VERSION,
        learning=_learning(db, current_user.id),
    )


def _learning(db: Session, tenant_id: str) -> LearningState:
    inputs = extraction.gather_inputs(db, tenant_id)
    return LearningState(
        mode=(settings.ECHO_SIGNAL_EXTRACTION or "off").lower(),
        inputs=len(inputs),
        by_language=extraction.inputs_by_language(inputs),
        pending=extraction.pending(db, tenant_id, inputs).count,
        threshold=settings.ECHO_SIGNALS_MIN_NEW_INPUTS,
        last_learned_at=_utc(extraction.last_learned_at(db, tenant_id)),
    )


def _utc(dt):
    """Stored naive in UTC; sent with its offset so the browser shows local time."""
    from datetime import timezone

    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


@router.post("/learn", response_model=LearnResponse, status_code=202)
def learn_now(db: Session = Depends(get_db), current_user: User = Depends(ECHO)):
    """"Learn now": queue a run for whatever is waiting, below the threshold too."""
    status = extraction.maybe_queue(db, current_user.id, force=True)
    return LearnResponse(status=status, pending=extraction.pending(db, current_user.id).count)


@router.get("/export")
def export_signals(db: Session = Depends(get_db), current_user: User = Depends(ECHO)):
    """The voice profile as a JSON download."""
    return JSONResponse(
        jsonable_encoder(signals.export_profile(db, current_user.id)),
        headers={"Content-Disposition": 'attachment; filename="echo-voice-profile.json"'},
    )


@router.post("", response_model=VoiceSignalItem, status_code=201)
def create_signal(body: VoiceSignalCreate, db: Session = Depends(get_db), current_user: User = Depends(ECHO)):
    try:
        row = signals.create(
            db,
            tenant_id=current_user.id,
            user_id=current_user.id,
            signal_type=body.signal_type,
            value=body.value,
            language=body.language,
            register=body.register_,
        )
    except signals.SignalError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _item(row)


@router.patch("/{signal_id}", response_model=VoiceSignalItem)
def patch_signal(
    signal_id: str,
    body: VoiceSignalPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(ECHO),
):
    # language / register: an explicit null clears it, an absent field keeps it.
    kwargs = {}
    if "language" in body.model_fields_set:
        kwargs["language"] = body.language
    if "register_" in body.model_fields_set:
        kwargs["register"] = body.register_
    try:
        row = signals.update(db, current_user.id, signal_id, value=body.value, weight=body.weight, **kwargs)
    except signals.SignalNotFound:
        raise HTTPException(status_code=404, detail="Signal not found")
    except signals.SignalError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _item(row)


@router.delete("/{signal_id}", response_model=VoiceSignalItem)
def reject_signal(signal_id: str, db: Session = Depends(get_db), current_user: User = Depends(ECHO)):
    """'That's not me.' The signal is tombstoned and never comes back."""
    try:
        row = signals.suppress(db, current_user.id, signal_id)
    except signals.SignalNotFound:
        raise HTTPException(status_code=404, detail="Signal not found")
    return _item(row)
