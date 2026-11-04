import asyncio
import json
import logging
from collections import defaultdict

import redis.asyncio as aioredis
from fastapi import WebSocket

from app.config import settings
from app.services.progress_service import NOTIFICATIONS_CHANNEL_PREFIX

logger = logging.getLogger(__name__)

# Delay between reconnect attempts when the Redis listener encounters an
# error. Kept short enough to recover quickly, long enough to avoid
# hot-looping against a down Redis instance.
_RECONNECT_DELAY_SECONDS = 5


class ConnectionManager:
    """Manages WebSocket connections and Redis pub/sub bridge.

    Two kinds of topic share the one socket: a job's (or Author output's)
    progress, ``job_progress:{id}``, and since T-8.3.3.8 a user's
    notifications, ``notifications:{tenant_id}``. A socket joins a user's
    notifications only as the user its token names (``routers/ws.py``), and
    a notification is routed by its CHANNEL, so no payload can address
    another user's sockets.
    """

    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        # T-8.3.3.8: tenant_id -> the sockets showing that user's bell.
        self._user_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._global_connections: set[WebSocket] = set()
        self._redis_task: asyncio.Task | None = None
        self._redis: aioredis.Redis | None = None

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a WebSocket connection and start Redis listener if needed."""
        await websocket.accept()
        self._global_connections.add(websocket)
        if self._redis_task is None or self._redis_task.done():
            self._redis_task = asyncio.create_task(self._redis_listener())

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove WebSocket from all subscriptions."""
        self._global_connections.discard(websocket)
        for job_id in list(self._connections.keys()):
            self._connections[job_id].discard(websocket)
            if not self._connections[job_id]:
                del self._connections[job_id]
        for tenant_id in list(self._user_connections.keys()):
            self._user_connections[tenant_id].discard(websocket)
            if not self._user_connections[tenant_id]:
                del self._user_connections[tenant_id]

    def subscribe(self, websocket: WebSocket, job_id: str) -> None:
        """Subscribe a WebSocket to a specific job's updates."""
        self._connections[job_id].add(websocket)

    def unsubscribe(self, websocket: WebSocket, job_id: str) -> None:
        """Unsubscribe a WebSocket from a specific job's updates."""
        self._connections[job_id].discard(websocket)
        if not self._connections[job_id]:
            del self._connections[job_id]

    def subscribe_notifications(self, websocket: WebSocket, tenant_id: str) -> None:
        """Send ``tenant_id``'s new-notification events to this socket. The
        caller passes the tenant its token authenticated, never one the
        client named."""
        self._user_connections[tenant_id].add(websocket)

    def unsubscribe_notifications(self, websocket: WebSocket, tenant_id: str) -> None:
        sockets = self._user_connections.get(tenant_id)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            del self._user_connections[tenant_id]

    async def broadcast_to_user(self, tenant_id: str, message: dict) -> None:
        """Send a message to every socket subscribed to ``tenant_id``'s notifications."""
        dead = []
        for ws in list(self._user_connections.get(tenant_id, set())):
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception("Failed to send a notification over WebSocket")
                dead.append(ws)
        for ws in dead:
            self.unsubscribe_notifications(ws, tenant_id)

    async def dispatch(self, channel: str, raw: str) -> None:
        """Route one pub/sub message to the sockets that asked for it.

        A notification goes to the user named by its channel
        (``notifications:{tenant_id}``); anything else is job progress,
        routed by its ``job_id``. Malformed payloads are skipped.
        """
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            logger.exception("Malformed pubsub payload; skipping")
            return
        if not isinstance(data, dict):
            return
        if channel.startswith(NOTIFICATIONS_CHANNEL_PREFIX):
            tenant_id = channel[len(NOTIFICATIONS_CHANNEL_PREFIX):]
            if tenant_id:
                await self.broadcast_to_user(tenant_id, data)
            return
        job_id = data.get("job_id")
        if job_id:
            await self.broadcast_to_job(job_id, data)

    async def broadcast_to_job(self, job_id: str, message: dict) -> None:
        """Send a message to all clients subscribed to a job."""
        dead = []
        for ws in self._connections.get(job_id, set()):
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception(f"Failed to send WebSocket message for job {job_id}")
                dead.append(ws)
        for ws in dead:
            self._connections[job_id].discard(ws)

    async def _run_pubsub(self) -> None:
        """Single-attempt pubsub subscription + message loop. Raises on failure."""
        self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = self._redis.pubsub()
        try:
            await pubsub.psubscribe("job_progress:*", f"{NOTIFICATIONS_CHANNEL_PREFIX}*")
            async for message in pubsub.listen():
                if message["type"] == "pmessage":
                    await self.dispatch(message["channel"], message["data"])
        finally:
            try:
                await pubsub.aclose()
            except Exception:
                logger.exception("Error closing Redis pubsub")
            if self._redis is not None:
                try:
                    await self._redis.aclose()
                except Exception:
                    logger.exception("Error closing Redis connection")
                self._redis = None

    async def _redis_listener(self) -> None:
        """Background task: listen to Redis pub/sub and forward to WebSockets.

        Runs a reconnect loop while there are active WebSocket clients. Any
        error in the pubsub subscription is logged and retried after a short
        delay rather than silently dropping the listener.
        """
        try:
            while self._global_connections:
                try:
                    await self._run_pubsub()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Redis listener error; will reconnect")
                    if not self._global_connections:
                        break
                    await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
        except asyncio.CancelledError:
            pass


manager = ConnectionManager()
