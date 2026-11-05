import json
import logging
from typing import NamedTuple

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState

from app.services import auth_service
from app.websocket.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


class _SocketSession(NamedTuple):
    """Who a socket's token signs in as, and how long for."""

    tenant_id: str
    # None for a token issued before sessions existed.
    jti: str | None
    # The token's `exp`, in epoch seconds. None if it carries none.
    expires_at: float | None


def _owns_job(tenant_id: str, job_id: str, session_factory=None) -> bool:
    """Whether ``tenant_id`` owns the progress stream ``job_id``.

    A stream id is a job id or, since S-6.7.1, an Author Studio output id:
    `generate_output` publishes on `job_progress:{output_id}`, the channel
    jobs already use, so the socket needs no second channel. Either way the
    caller must own the row.

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
        if (
            db.query(Job.id)
            .filter(Job.id == job_id, Job.tenant_id == tenant_id)
            .first()
            is not None
        ):
            return True
        from app.models.output import Output

        return (
            db.query(Output.id)
            .filter(Output.id == job_id, Output.user_id == tenant_id)
            .first()
            is not None
        )
    except Exception:
        logger.exception("ws: ownership check failed for job %s; denying", job_id)
        return False
    finally:
        if db is not None:
            db.close()


def _authenticate(token: str, session_factory=None) -> _SocketSession | None:
    """The session ``token`` signs in as, or None.

    The same check every HTTP bearer route makes
    (``auth_service.authenticate_access_token``, T-5.4.15): an access token,
    not the second-factor ticket; a session that is not revoked; a user that
    still exists. Until T-5.4.15 the handshake decoded the token itself and
    never looked at the session, so signing out, "sign out everywhere" or a
    password reset left the token opening this socket until it expired.

    Opens its own short-lived session, like ``_owns_job``, and fails CLOSED:
    a database error refuses the socket.
    """
    if session_factory is None:
        from app.database import SessionLocal

        session_factory = SessionLocal

    db = None
    try:
        db = session_factory()
        resolved = auth_service.authenticate_access_token(db, token)
        if resolved is None:
            return None
        user, payload = resolved
        jti = payload.get("jti")
        exp = payload.get("exp")
        return _SocketSession(
            user.id,
            jti if isinstance(jti, str) else None,
            exp if isinstance(exp, (int, float)) else None,
        )
    except Exception:
        logger.exception("ws: token check failed; refusing the socket")
        return None
    finally:
        if db is not None:
            db.close()


@router.websocket("/ws/jobs")
async def job_progress_ws(websocket: WebSocket, token: str | None = Query(default=None)):
    """
    Multiplexed WebSocket for job progress updates.

    Auth:
        Requires a valid JWT passed as ?token=... query parameter, from a
        session that is not revoked. Connection is closed with code 1008
        (policy violation) if missing/invalid, and with 1008 again when the
        session is revoked later (T-5.4.19): at once over Redis pub/sub, or
        within a minute if that message is lost (websocket/manager.py). The
        token expiring closes it the same way, within a minute (T-5.4.21).
        This is the one route that still reads a token from the URL (T-8.8.1.5,
        D-085 addendum): the browser WebSocket API cannot set an Authorization
        header on the handshake. Every HTTP route is header-only.

    Client messages:
        {"action": "subscribe", "job_id": "abc-123"}
        {"action": "unsubscribe", "job_id": "abc-123"}
        {"action": "subscribe", "topic": "notifications"}    (T-8.3.3.8)
        {"action": "unsubscribe", "topic": "notifications"}
        "ping"

    Server messages:
        Job progress/status/error events (see progress_service.py)
        {"type": "notification", "id": "...", "kind": "..."}: a new
            notification for the token's user; the bell refetches its list
        "pong"
    """
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
        return

    # An access token of a live session (T-5.4.15), checked as the HTTP
    # routes check theirs. The second-factor ticket is signed with the same
    # key and would otherwise open the socket before the code is sent.
    session = _authenticate(token)
    if session is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return
    tenant_id = session.tenant_id

    await manager.connect(websocket, tenant_id=tenant_id, jti=session.jti, expires_at=session.expires_at)
    try:
        while True:
            raw = await websocket.receive_text()
            if raw == "ping":
                await websocket.send_text("pong")
                continue

            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    continue
                action = msg.get("action")
                job_id = msg.get("job_id")

                if msg.get("topic") == "notifications" and action in ("subscribe", "unsubscribe"):
                    # T-8.3.3.8: the bell. Always the token's own user: the
                    # message names no user, and one it names is ignored.
                    if action == "subscribe":
                        manager.subscribe_notifications(websocket, tenant_id)
                    else:
                        manager.unsubscribe_notifications(websocket, tenant_id)
                elif action == "subscribe" and job_id:
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
        pass
    except RuntimeError:
        # T-5.4.19: the manager closes a revoked or expired socket from outside
        # this loop, so the next send or receive here can find it closed.
        if websocket.application_state != WebSocketState.DISCONNECTED:
            raise
    finally:
        await manager.disconnect(websocket)
