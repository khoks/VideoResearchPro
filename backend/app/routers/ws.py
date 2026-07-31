import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.services import auth_service
from app.websocket.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


def _owns_job(tenant_id: str, job_id: str, session_factory=None) -> bool:
    """Whether ``tenant_id`` owns ``job_id``.

    Opens its own short-lived session: this runs inside the socket loop, not a
    request, so there is no `Depends(get_db)` to lean on. ``session_factory``
    is injectable so the check can be exercised against a test database — the
    default resolves lazily to the app's real session maker.

    Fails CLOSED — any error denies the subscription rather than risk leaking
    another tenant's stream.
    """
    from app.models.job import Job

    if session_factory is None:
        from app.database import SessionLocal

        session_factory = SessionLocal

    db = None
    try:
        # Opening the session is inside the guard on purpose: a connection
        # failure must DENY, not raise out of the socket loop.
        db = session_factory()
        return (
            db.query(Job.id)
            .filter(Job.id == job_id, Job.tenant_id == tenant_id)
            .first()
            is not None
        )
    except Exception:
        logger.exception("ws: ownership check failed for job %s; denying", job_id)
        return False
    finally:
        if db is not None:
            db.close()


@router.websocket("/ws/jobs")
async def job_progress_ws(websocket: WebSocket, token: str | None = Query(default=None)):
    """
    Multiplexed WebSocket for job progress updates.

    Auth:
        Requires a valid JWT passed as ?token=... query parameter.
        Connection is closed with code 1008 (policy violation) if missing/invalid.

    Client messages:
        {"action": "subscribe", "job_id": "abc-123"}
        {"action": "unsubscribe", "job_id": "abc-123"}
        "ping"

    Server messages:
        Job progress/status/error events (see progress_service.py)
        "pong"
    """
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
        return

    payload = auth_service.decode_token(token)
    if not payload or not payload.get("sub"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    tenant_id = payload["sub"]
    await manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            if raw == "ping":
                await websocket.send_text("pong")
                continue

            try:
                msg = json.loads(raw)
                action = msg.get("action")
                job_id = msg.get("job_id")

                if action == "subscribe" and job_id:
                    # S-5.7.1: the socket previously subscribed to ANY job_id a
                    # client sent, so a valid token for user A streamed user B's
                    # progress, status messages and error text. Ownership is
                    # checked against the token's tenant before subscribing.
                    if not _owns_job(tenant_id, job_id):
                        logger.warning(
                            "ws: tenant %s attempted to subscribe to foreign job %s",
                            tenant_id, job_id,
                        )
                        continue
                    manager.subscribe(websocket, job_id)
                elif action == "unsubscribe" and job_id:
                    # Unsubscribe is safe unconditionally — it can only ever
                    # remove this socket from a topic it already holds.
                    manager.unsubscribe(websocket, job_id)
            except json.JSONDecodeError:
                logger.debug("Received non-JSON message on /ws/jobs")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
