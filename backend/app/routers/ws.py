import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.services import auth_service
from app.websocket.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


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
                    manager.subscribe(websocket, job_id)
                elif action == "unsubscribe" and job_id:
                    manager.unsubscribe(websocket, job_id)
            except json.JSONDecodeError:
                logger.debug("Received non-JSON message on /ws/jobs")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
