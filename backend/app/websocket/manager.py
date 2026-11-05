import asyncio
import json
import logging
import time
from collections import defaultdict
from collections.abc import Collection, Iterable

import redis.asyncio as aioredis
from fastapi import WebSocket, status

from app.config import settings
from app.services import auth_service
from app.services.progress_service import (
    NOTIFICATIONS_CHANNEL_PREFIX,
    SESSION_REVOKED_CHANNEL_PREFIX,
)

logger = logging.getLogger(__name__)

# Delay between reconnect attempts when the Redis listener encounters an
# error. Kept short enough to recover quickly, long enough to avoid
# hot-looping against a down Redis instance.
_RECONNECT_DELAY_SECONDS = 5

# T-5.4.19: how often open sockets are checked against the sessions table. A
# revocation normally closes its socket at once over pub/sub; this bounds the
# case where that message never arrived (Redis down when it was published, or
# this process between two subscriptions). T-5.4.21: the same tick closes a
# socket whose token has expired, so that happens within this long of `exp`.
_SESSION_RECHECK_SECONDS = 60


def _now() -> float:
    """Epoch seconds, the unit of a token's ``exp``. A seam for the tests."""
    return time.time()


def _revoked_among(jtis: Collection[str]) -> set[str]:
    """Which of ``jtis`` are revoked, in a session of its own: this runs in a
    background task, not a request. Resolved at call time, like the socket's
    own checks in ``routers/ws.py``."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return auth_service.revoked_jtis(db, jtis)
    finally:
        db.close()


class ConnectionManager:
    """Manages WebSocket connections and Redis pub/sub bridge.

    Two kinds of topic share the one socket: a job's (or Author output's)
    progress, ``job_progress:{id}``, and since T-8.3.3.8 a user's
    notifications, ``notifications:{tenant_id}``. A socket joins a user's
    notifications only as the user its token names (``routers/ws.py``), and
    a notification is routed by its CHANNEL, so no payload can address
    another user's sockets.

    Since T-5.4.19 a socket also ends with its session. Each socket is held
    with the session that opened it; a revocation is published on
    ``session_revoked:{tenant_id}`` so it reaches every API process, and each
    closes the sockets it holds on those sessions with 1008. A periodic look
    at the sessions table is the net under pub/sub, so with Redis down a
    revoked socket closes within ``_SESSION_RECHECK_SECONDS``.

    Since T-5.4.21 it also ends with its token. Each socket is held with the
    token's ``exp``, and the same tick closes one past it with 1008. That
    compares a number held here, so it needs neither the table nor Redis and
    goes on working while either is down.
    """

    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        # T-8.3.3.8: tenant_id -> the sockets showing that user's bell.
        self._user_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._global_connections: set[WebSocket] = set()
        # T-5.4.19: socket -> (tenant_id, jti) of the session that opened it.
        # A token with no `jti` predates sessions: nothing can revoke it.
        self._sessions: dict[WebSocket, tuple[str, str]] = {}
        # T-5.4.21: socket -> the `exp` of the token that opened it, in epoch
        # seconds. Kept apart from `_sessions`, since a token with no `jti`
        # still expires.
        self._expiries: dict[WebSocket, float] = {}
        self._session_check_task: asyncio.Task | None = None
        self._closing: set[asyncio.Task] = set()
        self._redis_task: asyncio.Task | None = None
        self._redis: aioredis.Redis | None = None

    async def connect(
        self,
        websocket: WebSocket,
        *,
        subprotocol: str | None = None,
        tenant_id: str | None = None,
        jti: str | None = None,
        expires_at: float | None = None,
    ) -> None:
        """Accept a WebSocket connection and start Redis listener if needed.
        ``subprotocol`` is the one the handshake's answer names, ``tenant_id``
        and ``jti`` name the session its token authenticated, and
        ``expires_at`` is that token's ``exp``."""
        await websocket.accept(subprotocol=subprotocol)
        self._global_connections.add(websocket)
        if tenant_id and jti:
            self._sessions[websocket] = (tenant_id, jti)
        if expires_at is not None:
            self._expiries[websocket] = expires_at
        if self._has_timed_sockets() and (
            self._session_check_task is None or self._session_check_task.done()
        ):
            self._session_check_task = asyncio.create_task(self._session_check_loop())
        if self._redis_task is None or self._redis_task.done():
            self._redis_task = asyncio.create_task(self._redis_listener())

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove WebSocket from all subscriptions."""
        self._global_connections.discard(websocket)
        self._sessions.pop(websocket, None)
        self._expiries.pop(websocket, None)
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

    async def close_sessions(self, tenant_id: str, jtis: Collection[str]) -> None:
        """Close the sockets this process holds on ``jtis`` of ``tenant_id``.
        The message goes to every process, so most hold none of them."""
        await self._close_sockets(
            (ws for ws, (owner, jti) in list(self._sessions.items()) if owner == tenant_id and jti in jtis),
            reason="Session revoked",
        )

    async def close_revoked_sessions(self) -> None:
        """The net under pub/sub: close every socket whose session the table
        says is revoked. A failed read leaves the sockets for the next one."""
        held = {jti for _, jti in self._sessions.values()}
        if not held:
            return
        try:
            revoked = await asyncio.to_thread(_revoked_among, held)
        except Exception:
            logger.exception("ws: session re-check failed; will try again")
            return
        await self._close_sockets(
            (ws for ws, (_, jti) in list(self._sessions.items()) if jti in revoked),
            reason="Session revoked",
        )

    async def close_expired_sockets(self) -> None:
        """Close every socket whose token has passed its ``exp`` (T-5.4.21)."""
        now = _now()
        await self._close_sockets(
            (ws for ws, expires_at in list(self._expiries.items()) if expires_at <= now),
            reason="Session expired",
        )

    async def _close_sockets(self, websockets: Iterable[WebSocket], *, reason: str) -> None:
        """Close them side by side: a close waits for the client's answer, up
        to the server's timeout, and one that never answers holds up nobody
        else."""

        async def _close(websocket: WebSocket) -> None:
            # Dropped first, so it hears nothing more whatever close does.
            await self.disconnect(websocket)
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
            except Exception:
                logger.debug("ws: socket already gone when its session ended")

        await asyncio.gather(*(_close(ws) for ws in websockets))

    def _has_timed_sockets(self) -> bool:
        """Whether any socket has a session to re-check or a token to outlive."""
        return bool(self._sessions or self._expiries)

    async def _session_check_loop(self) -> None:
        """Background task: runs while any socket holds a session or a token
        that can expire. Expiry goes first: it never touches the database, so
        a failing read cannot hold it up."""
        while self._has_timed_sockets():
            await asyncio.sleep(_SESSION_RECHECK_SECONDS)
            await self.close_expired_sockets()
            await self.close_revoked_sessions()

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
        (``notifications:{tenant_id}``), and a revocation closes that user's
        named sessions (``session_revoked:{tenant_id}``); anything else is
        job progress, routed by its ``job_id``. Malformed payloads are
        skipped.
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
        if channel.startswith(SESSION_REVOKED_CHANNEL_PREFIX):
            tenant_id = channel[len(SESSION_REVOKED_CHANNEL_PREFIX):]
            jtis = data.get("jtis")
            if tenant_id and isinstance(jtis, list):
                # In a task of its own: this loop carries every user's
                # progress, and a close can wait on a slow client.
                task = asyncio.create_task(
                    self.close_sessions(tenant_id, {j for j in jtis if isinstance(j, str)})
                )
                self._closing.add(task)
                task.add_done_callback(self._closing.discard)
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
            await pubsub.psubscribe(
                "job_progress:*",
                f"{NOTIFICATIONS_CHANNEL_PREFIX}*",
                f"{SESSION_REVOKED_CHANNEL_PREFIX}*",
            )
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
