import asyncio
import json
import logging
from collections import defaultdict

import redis.asyncio as aioredis
from fastapi import WebSocket

from app.config import settings

logger = logging.getLogger(__name__)

# Delay between reconnect attempts when the Redis listener encounters an
# error. Kept short enough to recover quickly, long enough to avoid
# hot-looping against a down Redis instance.
_RECONNECT_DELAY_SECONDS = 5


class ConnectionManager:
    """Manages WebSocket connections and Redis pub/sub bridge."""

    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
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

    def subscribe(self, websocket: WebSocket, job_id: str) -> None:
        """Subscribe a WebSocket to a specific job's updates."""
        self._connections[job_id].add(websocket)

    def unsubscribe(self, websocket: WebSocket, job_id: str) -> None:
        """Unsubscribe a WebSocket from a specific job's updates."""
        self._connections[job_id].discard(websocket)
        if not self._connections[job_id]:
            del self._connections[job_id]

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
            await pubsub.psubscribe("job_progress:*")
            async for message in pubsub.listen():
                if message["type"] == "pmessage":
                    try:
                        data = json.loads(message["data"])
                        job_id = data.get("job_id")
                        if job_id:
                            await self.broadcast_to_job(job_id, data)
                    except json.JSONDecodeError:
                        logger.exception("Malformed pubsub payload; skipping")
                        continue
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
