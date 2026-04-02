import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/jobs")
async def job_progress_ws(websocket: WebSocket):
    """
    Multiplexed WebSocket for job progress updates.

    Client messages:
        {"action": "subscribe", "job_id": "abc-123"}
        {"action": "unsubscribe", "job_id": "abc-123"}
        "ping"

    Server messages:
        Job progress/status/error events (see progress_service.py)
        "pong"
    """
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
                pass
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
