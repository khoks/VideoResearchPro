"""Sign-in and rate-limit follow-ups from #391 and #399, at the routers.

* T-5.4.16: ``DELETE /auth/mfa`` takes a capped number of codes, counted on
  the user in the database. Past the cap it answers 429 and checks nothing.
  A wrong code here never touches sign-in, and a right one clears the count.
* T-5.4.18: a NUL or lone surrogate in a password is a clean 4xx on register,
  reset and login, and nothing about the value reaches a response or a log.
* T-5.4.19: a real revoke route closes a real open socket, on all four paths.
  A revocation is published on Redis so any API process can close the socket;
  with Redis down it still stands, and the socket closes at the next look at
  the sessions table.
* T-5.5.8: ``X-Forwarded-For`` counts only from a proxy in
  ``TRUSTED_PROXY_IPS``, for the rate limiter, the audit log and the address
  stored on a session alike.
* T-5.6.10: the job and library clarify endpoints serve a Studio user on their
  own key. The shelf path already did, and its clarify is the library's.
* T-5.6.11: a well-formed key that cannot read a stored TOTP secret is
  reported as a malformed one is, not as a wrong code. Recovery codes work,
  and retrying a code the server cannot check costs no attempt.

Mutation checks (run when this shipped; each made the named test
fail, and the cheap ones are pinned as ``test_mutation_*``). One stays: taking
out the ``not networks`` early return in ``client_ip`` changes nothing, because
an empty list trusts no peer anyway. Among them: dropping the
``count_disable_attempt`` call or raising the cap
(``test_turning_off_takes_five_codes_then_checks_none``); counting a miss on
the account lockout (``test_a_wrong_code_here_does_not_touch_sign_in``);
keeping the row on a right code
(``test_a_right_code_clears_the_count``); dropping the guard from
``verify_password`` (``test_login_with_an_unstorable_password_logs_nothing``);
checking the password after the reset
(``test_a_refused_new_password_does_not_spend_the_reset_code``); dropping
``_announce_revoked`` from any of the four paths
(``test_a_real_revocation_closes_a_real_open_socket``); dropping the
``session_revoked`` pattern from ``psubscribe`` (the same test); leaving the
look out of its timer (``test_the_look_runs_on_a_timer_while_a_session_is_held``);
reading only the header's first line (``test_a_proxy_that_adds_its_own_line_is_read``);
the header's leftmost entry, as before T-5.5.8
(``test_a_client_cannot_spoof_past_the_proxy``); the old ``usage_service.metered``
scope on either clarify route (``test_clarify_is_served_on_the_askers_own_key``);
swallowing ``InvalidToken`` again (``test_a_rotated_key_reads_as_the_key_not_a_wrong_code``);
dropping the ``row.enabled`` check, or the router's 409 for it
(``test_the_setup_route_is_no_way_round_the_cap``); dropping the thinking reserve,
always clamping at the ceiling, or a bare 400 back on either route
(``test_clarify_leaves_room_for_the_reply_above_a_pins_thinking``); never clamping
(``test_a_ceiling_above_the_thinking_still_caps_the_reply``); ignoring a ceiling
for a provider that sends no budget
(``test_library.py::test_library_clarify_stays_within_the_models_output_limit``);
no refund on the 503
(``test_a_code_the_key_cannot_check_leaves_recovery_codes_reachable``); refunding
every 503, or answering the fifth with one, or not recording the miss
(``test_recovery_guesses_stay_counted_while_the_key_is_broken``); a refund that
clears the count (``test_a_code_that_was_not_checked_keeps_the_misses_before_it``);
the shape check reading the raw text (``test_the_shape_check_reads_what_the_hash_reads``).
"""
from __future__ import annotations

import asyncio
import fnmatch
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.job import Job
from app.models.mfa_secret import MfaSecret
from app.models.mfa_step_ticket import MfaStepTicket
from app.models.password_reset_token import PasswordResetToken
from app.models.session import Session as SessionRow
from app.models.user import User
from app.models.user_llm_override import UserLLMOverride
from app.routers import mfa as mfa_router
from app.services import (
    auth_service,
    byok_service,
    llm_service,
    mfa_service,
    progress_service,
    rate_limit_service,
    shelf_service,
)
from app.services.audit_service import ACCOUNT_EVENTS, Event
from app.services.llm_routing import UseCaseConfig, resolve_config
from app.utils import client_ip as client_ip_module
from app.utils.client_ip import client_ip, rate_limit_bucket
from app.websocket import manager as manager_module
from app.websocket.manager import ConnectionManager
from tests.conftest import TestingSessionLocal
from tests.test_routers.test_auth_hardening_followups import (
    LOGIN_MFA,
    PASSWORD,
    _auth,
    _break_the_key,
    _change,
    _events,
    _login,
    _meta,
    _mfa_user,
    _reset,
    _ticket,
    _wrong_code,
)
from tests.usage_helpers import CLARIFY_JSON, MeteredFakeChat, call_llm, metered_llms  # noqa: F401

MFA = "/api/v1/auth/mfa"
REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
RESET_CONFIRM = "/api/v1/auth/password-reset/confirm"


@pytest.fixture
def stable_key(monkeypatch):
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


def _rotate_the_key(monkeypatch) -> str:
    """A different well-formed key, as an operator who rotated it has."""
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", key)
    byok_service._get_fernet.cache_clear()
    return key


def _turn_off(client, token: str, code: str):
    return client.request("DELETE", MFA, json={"code": code}, headers=_auth(token))


def _session(db, user: User) -> str:
    token, _ = auth_service.create_access_token(user.id, db=db)
    return token


def _jti(token: str) -> str:
    return jwt.decode(token, options={"verify_signature": False})["jti"]


# ---------------------------------------------------------------------------
# T-5.4.16: DELETE /auth/mfa has an attempt cap
# ---------------------------------------------------------------------------


def test_turning_off_takes_five_codes_then_checks_none(unauthenticated_client, db, stable_key, monkeypatch):
    user, secret, _codes = _mfa_user(db, "off-cap@x.com")
    token = _session(db, user)
    wrong = _wrong_code(secret)

    for _ in range(4):
        r = _turn_off(unauthenticated_client, token, wrong)
        assert r.status_code == 400, r.text
    # The fifth, which uses up the cap, says so at once.
    r = _turn_off(unauthenticated_client, token, wrong)
    assert r.status_code == 429
    assert r.json()["detail"] == mfa_router.DISABLE_EXHAUSTED_DETAIL

    # Past the cap no code is checked, the right one included.
    checked = MagicMock(wraps=mfa_service.verify_at_login)
    monkeypatch.setattr(mfa_service, "verify_at_login", checked)
    r = _turn_off(unauthenticated_client, token, pyotp.TOTP(secret).now())
    assert r.status_code == 429
    checked.assert_not_called()
    assert mfa_service.is_enabled(db, user.id) is True


def test_mutation_without_the_cap_the_sixth_code_turns_it_off(unauthenticated_client, db, stable_key, monkeypatch):
    monkeypatch.setattr(mfa_service, "MFA_TICKET_MAX_ATTEMPTS", 10_000)
    user, secret, _codes = _mfa_user(db, "off-cap-mut@x.com")
    token = _session(db, user)
    for _ in range(5):
        assert _turn_off(unauthenticated_client, token, _wrong_code(secret)).status_code == 400
    assert _turn_off(unauthenticated_client, token, pyotp.TOTP(secret).now()).status_code == 200


def test_a_refusal_here_keeps_the_session(unauthenticated_client, db, stable_key):
    """A 429, never a 401: the web client signs out on a 401."""
    user, secret, _codes = _mfa_user(db, "off-keep@x.com")
    token = _session(db, user)
    for _ in range(mfa_service.MFA_TICKET_MAX_ATTEMPTS + 2):
        assert _turn_off(unauthenticated_client, token, _wrong_code(secret)).status_code in (400, 429)
    assert unauthenticated_client.get("/api/v1/auth/me", headers=_auth(token)).status_code == 200


def test_a_wrong_code_here_does_not_touch_sign_in(unauthenticated_client, db, stable_key):
    user, secret, _codes = _mfa_user(db, "off-lock@x.com")
    token = _session(db, user)
    for _ in range(mfa_service.MFA_TICKET_MAX_ATTEMPTS + 2):
        _turn_off(unauthenticated_client, token, _wrong_code(secret))

    db.expire_all()
    assert (db.get(User, user.id).failed_login_attempts or 0) == 0
    assert db.get(User, user.id).locked_until is None
    # The password step and a ticket's own count are both unaffected.
    ticket = _ticket(unauthenticated_client, "off-lock@x.com")
    r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200


def test_a_right_code_clears_the_count(unauthenticated_client, db, stable_key):
    user, secret, _codes = _mfa_user(db, "off-clear@x.com")
    token = _session(db, user)
    for _ in range(mfa_service.MFA_TICKET_MAX_ATTEMPTS - 1):
        _turn_off(unauthenticated_client, token, _wrong_code(secret))

    assert _turn_off(unauthenticated_client, token, pyotp.TOTP(secret).now()).status_code == 200
    db.expire_all()
    assert db.query(MfaStepTicket).count() == 0, "a right code clears the count"

    # Turned on again later, the count starts from nothing.
    secret2, _uri = mfa_service.enroll(db, user)
    mfa_service.verify_enrollment(db, user, pyotp.TOTP(secret2).now())
    assert _turn_off(unauthenticated_client, token, _wrong_code(secret2)).status_code == 400
    db.expire_all()
    assert db.query(MfaStepTicket).one().attempts == 1


def test_the_right_code_on_the_last_attempt_still_works(unauthenticated_client, db, stable_key):
    user, secret, _codes = _mfa_user(db, "off-last@x.com")
    token = _session(db, user)
    for _ in range(mfa_service.MFA_TICKET_MAX_ATTEMPTS - 1):
        _turn_off(unauthenticated_client, token, _wrong_code(secret))
    assert _turn_off(unauthenticated_client, token, pyotp.TOTP(secret).now()).status_code == 200


def test_the_count_follows_the_user_not_the_session(unauthenticated_client, db, stable_key):
    user, secret, _codes = _mfa_user(db, "off-user@x.com")
    other, other_secret, _ = _mfa_user(db, "off-other@x.com")
    for _ in range(mfa_service.MFA_TICKET_MAX_ATTEMPTS):
        _turn_off(unauthenticated_client, _session(db, user), _wrong_code(secret))

    # A new session of the same user starts no new count.
    assert _turn_off(unauthenticated_client, _session(db, user), pyotp.TOTP(secret).now()).status_code == 429
    # Another user is untouched.
    assert _turn_off(unauthenticated_client, _session(db, other), pyotp.TOTP(other_secret).now()).status_code == 200


def test_the_count_lasts_a_window_and_then_starts_over(unauthenticated_client, db, stable_key):
    user, secret, _codes = _mfa_user(db, "off-window@x.com")
    token = _session(db, user)
    for _ in range(mfa_service.MFA_TICKET_MAX_ATTEMPTS):
        _turn_off(unauthenticated_client, token, _wrong_code(secret))
    row = db.query(MfaStepTicket).one()
    until = row.expires_at - datetime.now(timezone.utc).replace(tzinfo=None)
    assert timedelta(minutes=mfa_service.MFA_DISABLE_WINDOW_MIN - 1) < until <= timedelta(
        minutes=mfa_service.MFA_DISABLE_WINDOW_MIN
    )

    row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db.commit()
    assert _turn_off(unauthenticated_client, token, pyotp.TOTP(secret).now()).status_code == 200


def test_a_later_miss_does_not_extend_the_window(unauthenticated_client, db, stable_key):
    user, secret, _codes = _mfa_user(db, "off-extend@x.com")
    token = _session(db, user)
    _turn_off(unauthenticated_client, token, _wrong_code(secret))
    first = db.query(MfaStepTicket).one().expires_at
    _turn_off(unauthenticated_client, token, _wrong_code(secret))
    db.expire_all()
    assert db.query(MfaStepTicket).one().expires_at == first


def test_refusals_are_audited_up_to_the_cap_and_no_further(unauthenticated_client, db, stable_key):
    """A session can send these as fast as it likes, so past the cap they
    write nothing."""
    user, secret, _codes = _mfa_user(db, "off-audit@x.com")
    token = _session(db, user)
    for _ in range(mfa_service.MFA_TICKET_MAX_ATTEMPTS + 3):
        _turn_off(unauthenticated_client, token, _wrong_code(secret))

    rows = _events(db, Event.MFA_DISABLE_FAILED, user.id)
    assert len(rows) == mfa_service.MFA_TICKET_MAX_ATTEMPTS
    assert _meta(rows[0])["reason"] == "invalid_code"
    assert _meta(rows[-1])["reason"] == "too_many_attempts"
    assert Event.MFA_DISABLE_FAILED in ACCOUNT_EVENTS, "the security page lists it"


def test_turning_off_when_it_is_already_off_counts_nothing(unauthenticated_client, db):
    user = auth_service.create_user(db, email="off-idem@x.com", password=PASSWORD)
    r = _turn_off(unauthenticated_client, _session(db, user), "123456")
    assert r.status_code == 200 and r.json() == {"disabled": True}
    assert db.query(MfaStepTicket).count() == 0


def _confirm_setup(client, token: str, code: str):
    return client.post(f"{MFA}/verify-enrollment", json={"code": code}, headers=_auth(token))


def test_the_setup_route_is_no_way_round_the_cap(unauthenticated_client, db, stable_key, monkeypatch):
    """It takes a session and no ticket, so on an account already on it was an
    uncounted way to guess the live secret, and a match replaced the recovery
    codes, which then turned the second factor off. Once it is on, the route
    checks nothing: the right code gets the same 409 as a wrong one."""
    user, secret, codes = _mfa_user(db, "off-reconfirm@x.com")
    token = _session(db, user)
    stored = db.query(MfaSecret).filter(MfaSecret.user_id == user.id).one().recovery_codes_json
    enabled_events = len(_events(db, Event.MFA_ENABLED, user.id))
    checked = MagicMock(wraps=mfa_service._verify_totp_against_row)
    monkeypatch.setattr(mfa_service, "_verify_totp_against_row", checked)

    for code in (_wrong_code(secret), pyotp.TOTP(secret).now()):
        r = _confirm_setup(unauthenticated_client, token, code)
        assert r.status_code == 409, r.text
        assert "recovery_codes" not in r.json()
    checked.assert_not_called()

    db.expire_all()
    row = db.query(MfaSecret).filter(MfaSecret.user_id == user.id).one()
    assert row.recovery_codes_json == stored
    assert row.enabled is True
    assert len(_events(db, Event.MFA_ENABLED, user.id)) == enabled_events
    # The owner's codes are still the ones that work.
    assert _turn_off(unauthenticated_client, token, codes[0]).status_code == 200


def test_a_setup_in_flight_still_takes_a_code(unauthenticated_client, db, stable_key):
    """Only an account already on is refused: an in-flight secret guards
    nothing yet, so the first code is still checked as before."""
    user = auth_service.create_user(db, email="off-inflight@x.com", password=PASSWORD)
    secret, _uri = mfa_service.enroll(db, user)
    token = _session(db, user)
    assert _confirm_setup(unauthenticated_client, token, _wrong_code(secret)).status_code == 400
    r = _confirm_setup(unauthenticated_client, token, pyotp.TOTP(secret).now())
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == mfa_service.RECOVERY_CODE_COUNT


# ---------------------------------------------------------------------------
# T-5.4.18: a password bcrypt cannot read
# ---------------------------------------------------------------------------

NUL_PASSWORD = "abc\x00defgh1"
# Sent as raw JSON: json.dumps would escape it, and the escape is the point.
SURROGATE_BODY = '{"email": "%s", "%s": "abc\\ud800defgh1"%s}'


def _post_raw(client, path: str, raw: str):
    return client.post(path, content=raw, headers={"Content-Type": "application/json"})


@pytest.fixture
def auth_log(monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(auth_service, "logger", log)
    return log


def test_register_refuses_a_nul_and_stores_nothing(unauthenticated_client, db, auth_log):
    r = unauthenticated_client.post(REGISTER, json={"email": "nul-reg@x.com", "password": NUL_PASSWORD})
    assert r.status_code == 400
    assert r.json()["detail"] == auth_service.PASSWORD_CANNOT_BE_STORED
    assert "defgh" not in r.text
    assert db.query(User).filter(User.email == "nul-reg@x.com").count() == 0
    assert auth_log.mock_calls == []


def test_mutation_without_the_check_register_is_a_bare_500(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(auth_service, "password_can_be_hashed", lambda _password: True)
    with pytest.raises(Exception):
        unauthenticated_client.post(REGISTER, json={"email": "nul-mut@x.com", "password": NUL_PASSWORD})


def test_register_refuses_a_lone_surrogate_cleanly(unauthenticated_client, db):
    r = _post_raw(unauthenticated_client, REGISTER, SURROGATE_BODY % ("sur-reg@x.com", "password", ""))
    assert 400 <= r.status_code < 500
    assert "defgh" not in r.text
    assert db.query(User).filter(User.email == "sur-reg@x.com").count() == 0


def test_a_refused_new_password_does_not_spend_the_reset_code(unauthenticated_client, db, monkeypatch):
    from tests.test_routers.test_auth_hardening import _reset_secret

    auth_service.create_user(db, email="nul-reset@x.com", password=PASSWORD)
    secret = _reset_secret(unauthenticated_client, monkeypatch, "nul-reset@x.com")

    r = unauthenticated_client.post(RESET_CONFIRM, json={"token": secret, "new_password": NUL_PASSWORD})
    assert r.status_code == 400
    assert r.json()["detail"] == auth_service.PASSWORD_CANNOT_BE_STORED
    assert "defgh" not in r.text
    db.expire_all()
    assert db.query(PasswordResetToken).one().consumed_at is None
    assert _login(unauthenticated_client, "nul-reset@x.com"), "the old password still signs in"

    # The reader fixes the password and the same code works.
    r = unauthenticated_client.post(RESET_CONFIRM, json={"token": secret, "new_password": "fixed-pw-123"})
    assert r.status_code == 200


def test_reset_refuses_a_lone_surrogate_cleanly(unauthenticated_client, db):
    raw = '{"token": "abcdefghij", "new_password": "abc\\ud800defgh1"}'
    r = _post_raw(unauthenticated_client, RESET_CONFIRM, raw)
    assert 400 <= r.status_code < 500
    assert "defgh" not in r.text


@pytest.mark.parametrize("email", ["nul-login@x.com", "nobody@x.com"])
def test_login_with_an_unstorable_password_logs_nothing(unauthenticated_client, db, auth_log, email):
    """It reads as a wrong password, with the same body for a known and an
    unknown address, and bcrypt never sees it: its exception used to reach
    the log with the character's position in it."""
    auth_service.create_user(db, email="nul-login@x.com", password=PASSWORD)
    r = unauthenticated_client.post(LOGIN, json={"email": email, "password": NUL_PASSWORD})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"
    assert auth_log.mock_calls == []


def test_login_refuses_a_lone_surrogate_cleanly(unauthenticated_client, db, auth_log):
    auth_service.create_user(db, email="sur-login@x.com", password=PASSWORD)
    r = _post_raw(unauthenticated_client, LOGIN, SURROGATE_BODY % ("sur-login@x.com", "password", ""))
    assert 400 <= r.status_code < 500
    assert "defgh" not in r.text
    assert auth_log.mock_calls == []


def test_an_unstorable_password_at_sign_in_counts_as_a_miss(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(settings, "LOCKOUT_FAILURE_THRESHOLD", 2)
    user = auth_service.create_user(db, email="nul-lock@x.com", password=PASSWORD)
    for _ in range(2):
        unauthenticated_client.post(LOGIN, json={"email": "nul-lock@x.com", "password": NUL_PASSWORD})
    db.expire_all()
    assert db.get(User, user.id).locked_until is not None


@pytest.mark.parametrize("path", [REGISTER, LOGIN, RESET_CONFIRM])
def test_bytes_that_are_not_utf8_are_a_refusal(unauthenticated_client, db, path):
    # UTF-8 refuses to encode a surrogate; here the raw bytes try anyway.
    raw = b'{"email": "bytes@x.com", "token": "abcdefghij", "password": "abc\xed\xa0\x80defgh1", "new_password": "abc\xed\xa0\x80defgh1"}'
    r = unauthenticated_client.post(path, content=raw, headers={"Content-Type": "application/json"})
    assert 400 <= r.status_code < 500
    assert "defgh" not in r.text


# ---------------------------------------------------------------------------
# T-5.4.19: a revoked session's open socket closes
# ---------------------------------------------------------------------------


class _PubSub:
    def __init__(self, bus):
        self.bus = bus
        self.patterns: tuple[str, ...] = ()
        self.queue: asyncio.Queue | None = None

    async def psubscribe(self, *patterns):
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        self.patterns = patterns
        self.bus.subscribers.append(self)
        self.bus.ready.set()

    def deliver(self, channel, raw):
        if any(fnmatch.fnmatchcase(channel, p) for p in self.patterns):
            message = {"type": "pmessage", "channel": channel, "data": raw}
            self.loop.call_soon_threadsafe(self.queue.put_nowait, message)

    async def listen(self):
        while True:
            yield await self.queue.get()

    async def aclose(self):
        self.bus.subscribers.remove(self)


class _Bus:
    """Redis pub/sub in memory: the publisher side ``progress_service`` talks
    to and the listener side the manager talks to, so everything between the
    route and the socket is the production code."""

    def __init__(self):
        self.subscribers: list[_PubSub] = []
        self.ready = threading.Event()
        self.down = False
        self.published: list[tuple[str, str]] = []

    def publish(self, channel, raw):
        if self.down:
            raise ConnectionError("redis is down")
        self.published.append((channel, raw))
        for subscriber in list(self.subscribers):
            subscriber.deliver(channel, raw)
        return len(self.subscribers)

    def pubsub(self):
        return _PubSub(self)

    async def aclose(self):
        pass


@pytest.fixture
def live(db, monkeypatch):
    """A real ``ConnectionManager`` behind ``/ws/jobs``, on the in-memory bus."""
    bus = _Bus()
    manager = ConnectionManager()
    monkeypatch.setattr("app.database.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("app.routers.ws.manager", manager)
    monkeypatch.setattr("app.websocket.manager.aioredis.from_url", lambda *a, **k: bus)
    monkeypatch.setattr(progress_service, "_get_redis", lambda: bus)
    bus.manager = manager
    return bus


def _open(client, token: str):
    return client.websocket_connect("/ws/jobs", subprotocols=["bearer", token])


def _pong(ws) -> None:
    ws.send_text("ping")
    assert ws.receive_text() == "pong"


def _closed_with(ws, within: float = 5.0) -> tuple[int, str] | None:
    """The code and reason ``ws`` closes with, or None if it is still open
    after ``within`` seconds. A thread, because a receive has no timeout and
    a socket that never closes must fail the test, not hang the suite."""
    seen: list[tuple[int, str]] = []

    def _read():
        try:
            while True:
                ws.receive_text()
        except WebSocketDisconnect as exc:
            seen.append((exc.code, exc.reason))
        except Exception:
            pass

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    reader.join(within)
    return seen[0] if seen else None


@pytest.mark.parametrize(
    "how", ["one_session", "sign_out", "sign_out_everywhere", "password_reset", "password_change"]
)
def test_a_real_revocation_closes_a_real_open_socket(unauthenticated_client, db, live, monkeypatch, how):
    client = unauthenticated_client
    email = f"sock-{how.replace('_', '-')}@x.com"
    auth_service.create_user(db, email=email, password=PASSWORD)
    target = _login(client, email)
    other = _login(client, email)

    with _open(client, target) as ws:
        assert live.ready.wait(5)
        _pong(ws)
        if how == "one_session":
            r = client.delete(f"/api/v1/auth/sessions/{_jti(target)}", headers=_auth(other))
        elif how == "sign_out":
            r = client.post("/api/v1/auth/logout", headers=_auth(target))
        elif how == "sign_out_everywhere":
            r = client.delete("/api/v1/auth/sessions", headers=_auth(other))
        elif how == "password_reset":
            r = _reset(client, monkeypatch, email)
        else:
            r = _change(client, other, PASSWORD, "brand-new-pw")
        assert r.status_code == 200, r.text

        assert _closed_with(ws) == (1008, "Session revoked")

    assert live.manager._sessions == {}


def test_only_the_revoked_session_closes(unauthenticated_client, db, live):
    client = unauthenticated_client
    auth_service.create_user(db, email="sock-one@x.com", password=PASSWORD)
    gone, kept = _login(client, "sock-one@x.com"), _login(client, "sock-one@x.com")
    with _open(client, gone) as ws_gone, _open(client, kept) as ws_kept:
        assert live.ready.wait(5)
        assert client.delete(f"/api/v1/auth/sessions/{_jti(gone)}", headers=_auth(kept)).status_code == 200
        assert _closed_with(ws_gone) == (1008, "Session revoked")
        _pong(ws_kept)


@pytest.mark.parametrize("how", ["keep_current", "password_change"])
def test_the_session_that_asked_keeps_its_socket(unauthenticated_client, db, live, how):
    client = unauthenticated_client
    email = f"sock-keep-{how.replace('_', '-')}@x.com"
    auth_service.create_user(db, email=email, password=PASSWORD)
    here, elsewhere = _login(client, email), _login(client, email)
    with _open(client, here) as ws_here, _open(client, elsewhere) as ws_elsewhere:
        assert live.ready.wait(5)
        if how == "keep_current":
            r = client.delete("/api/v1/auth/sessions?keep_current=true", headers=_auth(here))
        else:
            r = _change(client, here, PASSWORD, "brand-new-pw")
        assert r.status_code == 200, r.text
        assert _closed_with(ws_elsewhere) == (1008, "Session revoked")
        _pong(ws_here)


def test_a_revocation_is_published_only_after_it_commits(unauthenticated_client, db, live, monkeypatch):
    """A listener that reads the table on hearing the message must find it
    revoked."""
    client = unauthenticated_client
    auth_service.create_user(db, email="sock-order@x.com", password=PASSWORD)
    token = _login(client, "sock-order@x.com")
    seen: list[bool] = []
    publish = live.publish

    def _checking_publish(channel, raw):
        check = TestingSessionLocal()
        try:
            seen.append(auth_service.is_session_active(check, _jti(token)))
        finally:
            check.close()
        return publish(channel, raw)

    monkeypatch.setattr(live, "publish", _checking_publish)
    client.post("/api/v1/auth/logout", headers=_auth(token))
    assert seen == [False]


def test_the_message_names_the_user_in_its_channel(unauthenticated_client, db, live):
    client = unauthenticated_client
    user = auth_service.create_user(db, email="sock-chan@x.com", password=PASSWORD)
    token = _login(client, "sock-chan@x.com")
    client.post("/api/v1/auth/logout", headers=_auth(token))
    assert live.published == [
        (f"session_revoked:{user.id}", json.dumps({"jtis": [_jti(token)]}))
    ]


def test_mutation_without_the_publish_the_socket_stays_open(unauthenticated_client, db, live, monkeypatch):
    monkeypatch.setattr(auth_service, "_announce_revoked", lambda *a, **k: None)
    client = unauthenticated_client
    auth_service.create_user(db, email="sock-mut@x.com", password=PASSWORD)
    token = _login(client, "sock-mut@x.com")
    other = _login(client, "sock-mut@x.com")
    with _open(client, token) as ws:
        assert live.ready.wait(5)
        client.delete(f"/api/v1/auth/sessions/{_jti(token)}", headers=_auth(other))
        time.sleep(0.2)
        _pong(ws)


def test_with_redis_down_the_revocation_stands_and_the_socket_closes_later(unauthenticated_client, db, live):
    client = unauthenticated_client
    auth_service.create_user(db, email="sock-down@x.com", password=PASSWORD)
    token = _login(client, "sock-down@x.com")
    other = _login(client, "sock-down@x.com")
    live.down = True

    with _open(client, token) as ws:
        r = client.delete(f"/api/v1/auth/sessions/{_jti(token)}", headers=_auth(other))
        assert r.status_code == 200, "a revocation never waits on Redis"
        assert client.get("/api/v1/auth/me", headers=_auth(token)).status_code == 401
        assert live.published == []
        _pong(ws)  # nothing has told this socket yet

        ws.portal.call(live.manager.close_revoked_sessions)

        assert _closed_with(ws) == (1008, "Session revoked")


def test_a_session_still_live_survives_the_look(unauthenticated_client, db, live):
    client = unauthenticated_client
    auth_service.create_user(db, email="sock-live@x.com", password=PASSWORD)
    token = _login(client, "sock-live@x.com")
    with _open(client, token) as ws:
        ws.portal.call(live.manager.close_revoked_sessions)
        _pong(ws)


def test_a_client_message_after_the_close_does_not_crash_the_handler(unauthenticated_client, db, live):
    """The manager closes from outside the read loop, so the loop can meet a
    closed socket on its next send. The session's exit re-raises anything the
    handler raised."""
    client = unauthenticated_client
    auth_service.create_user(db, email="sock-race@x.com", password=PASSWORD)
    token = _login(client, "sock-race@x.com")
    with _open(client, token) as ws:
        assert live.ready.wait(5)
        client.post("/api/v1/auth/logout", headers=_auth(token))
        assert _closed_with(ws) == (1008, "Session revoked")
        ws.send_text("ping")


class _Socket:
    """A socket stand-in that records how it was closed."""

    def __init__(self, fail=False):
        self.closed: tuple[int, str] | None = None
        self.fail = fail

    async def accept(self, subprotocol=None):
        pass

    async def close(self, code, reason):
        if self.fail:
            raise RuntimeError("socket gone")
        self.closed = (code, reason)


def _connected(manager, *sockets):
    """Register ``(socket, tenant, jti)`` triples without starting background
    tasks, which would outlive ``asyncio.run``."""
    for socket, tenant, jti in sockets:
        manager._global_connections.add(socket)
        if tenant and jti:
            manager._sessions[socket] = (tenant, jti)


def _dispatched(manager, channel: str, raw: str) -> None:
    """``manager.dispatch``, then whatever closes it started."""

    async def _go():
        await manager.dispatch(channel, raw)
        await asyncio.gather(*manager._closing)

    asyncio.run(_go())


def test_a_payload_cannot_reach_another_users_socket():
    m = ConnectionManager()
    mine, theirs = _Socket(), _Socket()
    _connected(m, (mine, "user-a", "jti-a"), (theirs, "user-b", "jti-b"))

    # user-b's session, named on user-a's channel: the channel decides.
    _dispatched(m, "session_revoked:user-a", json.dumps({"jtis": ["jti-b"]}))
    assert theirs.closed is None

    _dispatched(m, "session_revoked:user-a", json.dumps({"jtis": ["jti-a"]}))
    assert mine.closed == (1008, "Session revoked")


def test_a_client_that_never_answers_a_close_holds_nobody_up():
    """A close waits for the client. The pub/sub loop carries every user's
    progress, so it does not wait with it, and neither does the other socket."""

    class _Stuck(_Socket):
        async def close(self, code, reason):
            await asyncio.Event().wait()

    async def _go():
        m = ConnectionManager()
        stuck, ok = _Stuck(), _Socket()
        _connected(m, (stuck, "user-a", "jti-a"), (ok, "user-a", "jti-b"))
        await asyncio.wait_for(m.dispatch("session_revoked:user-a", json.dumps({"jtis": ["jti-a", "jti-b"]})), 1)
        for _ in range(5):
            await asyncio.sleep(0)
        assert ok.closed == (1008, "Session revoked")
        assert m._sessions == {}
        for task in m._closing:
            task.cancel()

    asyncio.run(_go())


def test_a_publish_is_bounded():
    kwargs = progress_service._redis_pool.connection_kwargs
    assert kwargs["socket_connect_timeout"] == kwargs["socket_timeout"] == progress_service._PUBLISH_TIMEOUT_SECONDS


@pytest.mark.parametrize("raw", ["not json", "[]", '{"jtis": "jti-a"}', "{}", '{"jtis": [1, {"a": 2}]}'])
def test_a_malformed_revocation_is_skipped(raw):
    m = ConnectionManager()
    socket = _Socket()
    _connected(m, (socket, "user-a", "jti-a"))
    _dispatched(m, "session_revoked:user-a", raw)
    assert socket.closed is None


def test_a_socket_already_gone_is_dropped_quietly():
    m = ConnectionManager()
    socket = _Socket(fail=True)
    _connected(m, (socket, "user-a", "jti-a"))
    asyncio.run(m.close_sessions("user-a", {"jti-a"}))
    assert m._sessions == {} and m._global_connections == set()


def test_a_failed_read_of_the_table_closes_nothing(monkeypatch):
    def _down(_jtis):
        raise RuntimeError("db down")

    monkeypatch.setattr(manager_module, "_revoked_among", _down)
    m = ConnectionManager()
    socket = _Socket()
    _connected(m, (socket, "user-a", "jti-a"))
    asyncio.run(m.close_revoked_sessions())
    assert socket.closed is None and socket in m._sessions


def test_the_look_runs_on_a_timer_while_a_session_is_held(monkeypatch):
    monkeypatch.setattr(manager_module, "_SESSION_RECHECK_SECONDS", 0.01)
    m = ConnectionManager()
    _connected(m, (_Socket(), "user-a", "jti-a"))
    looks: list[int] = []

    async def _look():
        looks.append(1)
        if len(looks) == 3:
            m._sessions.clear()

    m.close_revoked_sessions = _look
    asyncio.run(asyncio.wait_for(m._session_check_loop(), 2))
    assert len(looks) == 3, "it stops when no socket holds a session"


def test_connecting_with_a_session_starts_the_timer():
    async def _nothing():
        return None

    async def _go():
        m = ConnectionManager()
        m._redis_listener = _nothing
        await m.connect(_Socket(), tenant_id="user-a", jti="jti-a")
        assert m._session_check_task is not None and not m._session_check_task.done()
        m._session_check_task.cancel()

    asyncio.run(_go())


def test_a_token_from_before_sessions_is_held_with_no_session():
    """Nothing can revoke it, so there is nothing to look up."""

    async def _nothing():
        return None

    m = ConnectionManager()
    m._redis_listener = _nothing
    asyncio.run(m.connect(_Socket(), tenant_id="user-a", jti=None))
    assert m._sessions == {} and m._session_check_task is None


# ---------------------------------------------------------------------------
# T-5.4.21: a socket ends when its token does
#
# Mutation checks (each failed the named test when this shipped): leaving
# `close_expired_sockets` out of the timer
# (`test_a_real_token_expiring_closes_its_real_socket`); passing no
# `expires_at` from the route (the same test); `<` for `<=`
# (`test_a_token_at_its_exp_is_over`); keeping the timer on `_sessions` alone
# (`test_a_token_from_before_sessions_still_expires`); not forgetting the
# expiry on disconnect (`test_a_closed_socket_is_forgotten`).
# ---------------------------------------------------------------------------


def _short_token(db, user, seconds: int) -> str:
    token, _ = auth_service.create_access_token(user.id, db=db, expires_delta=timedelta(seconds=seconds))
    return token


def test_a_real_token_expiring_closes_its_real_socket(unauthenticated_client, db, live, monkeypatch):
    """The real route, token and timer. Only the clock moves, so a slow run
    cannot expire the token before the handshake reads it."""
    monkeypatch.setattr(manager_module, "_SESSION_RECHECK_SECONDS", 0.05)
    user = auth_service.create_user(db, email="sock-exp@x.com", password=PASSWORD)
    token = _short_token(db, user, 3600)
    with _open(unauthenticated_client, token) as ws:
        _pong(ws)
        time.sleep(0.2)  # several ticks, with the token still good
        _pong(ws)
        exp = auth_service.decode_token(token)["exp"]
        monkeypatch.setattr(manager_module, "_now", lambda: exp + 1)
        assert _closed_with(ws) == (1008, "Session expired")
    assert live.manager._sessions == {} and live.manager._expiries == {}


def test_the_look_leaves_a_live_token_open(unauthenticated_client, db, live):
    user = auth_service.create_user(db, email="sock-exp2@x.com", password=PASSWORD)
    with _open(unauthenticated_client, _short_token(db, user, 3600)) as ws:
        ws.portal.call(live.manager.close_expired_sockets)
        _pong(ws)


def test_the_socket_is_held_with_the_tokens_own_exp(unauthenticated_client, db, live):
    user = auth_service.create_user(db, email="sock-exp3@x.com", password=PASSWORD)
    token = _short_token(db, user, 3600)
    with _open(unauthenticated_client, token) as ws:
        _pong(ws)
        assert list(live.manager._expiries.values()) == [auth_service.decode_token(token)["exp"]]


def test_an_expired_token_still_cannot_open_one(unauthenticated_client, db, live):
    user = auth_service.create_user(db, email="sock-exp4@x.com", password=PASSWORD)
    with pytest.raises(WebSocketDisconnect) as refused:
        with _open(unauthenticated_client, _short_token(db, user, -5)):
            pass
    assert refused.value.code == 1008


def test_a_token_at_its_exp_is_over(monkeypatch):
    m = ConnectionManager()
    socket = _Socket()
    _connected(m, (socket, "user-a", "jti-a"))
    m._expiries[socket] = 1000
    monkeypatch.setattr(manager_module, "_now", lambda: 999.9)
    asyncio.run(m.close_expired_sockets())
    assert socket.closed is None
    monkeypatch.setattr(manager_module, "_now", lambda: 1000.0)
    asyncio.run(m.close_expired_sockets())
    assert socket.closed == (1008, "Session expired")


def test_a_token_from_before_sessions_still_expires():
    """It has no `jti`, so `_sessions` never holds it. The timer has to run."""

    async def _nothing():
        return None

    async def _go():
        m = ConnectionManager()
        m._redis_listener = _nothing
        await m.connect(_Socket(), tenant_id="user-a", jti=None, expires_at=1)
        assert m._sessions == {} and m._session_check_task is not None
        m._session_check_task.cancel()

    asyncio.run(_go())


def test_a_token_with_no_exp_is_held_with_none():
    """PyJWT accepts one, and nothing here issues one: no timer to run."""

    async def _nothing():
        return None

    m = ConnectionManager()
    m._redis_listener = _nothing
    asyncio.run(m.connect(_Socket(), tenant_id="user-a", jti=None, expires_at=None))
    assert m._expiries == {} and m._session_check_task is None


def test_the_timer_closes_expired_sockets_and_stops(monkeypatch):
    monkeypatch.setattr(manager_module, "_SESSION_RECHECK_SECONDS", 0.01)
    m = ConnectionManager()
    socket = _Socket()
    _connected(m, (socket, None, None))
    m._expiries[socket] = 1
    asyncio.run(asyncio.wait_for(m._session_check_loop(), 2))
    assert socket.closed == (1008, "Session expired")
    assert m._expiries == {}


def test_expiry_needs_neither_the_table_nor_redis(monkeypatch):
    """The read failing leaves revoked sockets for the next tick. An expired
    one goes regardless: it compares a number held here."""
    monkeypatch.setattr(manager_module, "_SESSION_RECHECK_SECONDS", 0.01)

    def _no_database(jtis):
        raise RuntimeError("database is down")

    monkeypatch.setattr(manager_module, "_revoked_among", _no_database)
    m = ConnectionManager()
    expired, live_one = _Socket(), _Socket()
    _connected(m, (expired, "user-a", "jti-a"), (live_one, "user-b", "jti-b"))
    m._expiries[expired] = 1
    m._expiries[live_one] = 9_999_999_999

    async def _go():
        task = asyncio.create_task(m._session_check_loop())
        await asyncio.sleep(0.1)
        assert not task.done(), "a failing read must not end the timer"
        task.cancel()

    asyncio.run(_go())
    assert expired.closed == (1008, "Session expired")
    assert live_one.closed is None


def test_one_socket_failing_to_close_stops_no_other(monkeypatch):
    m = ConnectionManager()
    broken, fine = _Socket(fail=True), _Socket()
    _connected(m, (broken, "user-a", "jti-a"), (fine, "user-b", "jti-b"))
    m._expiries.update({broken: 1, fine: 1})
    asyncio.run(m.close_expired_sockets())
    assert fine.closed == (1008, "Session expired")
    assert m._expiries == {} and m._sessions == {}


def test_a_closed_socket_is_forgotten():
    m = ConnectionManager()
    socket = _Socket()
    _connected(m, (socket, "user-a", "jti-a"))
    m._expiries[socket] = 1
    asyncio.run(m.disconnect(socket))
    assert m._expiries == {}


def test_a_revocation_still_says_revoked():
    m = ConnectionManager()
    socket = _Socket()
    _connected(m, (socket, "user-a", "jti-a"))
    asyncio.run(m.close_sessions("user-a", {"jti-a"}))
    assert socket.closed == (1008, "Session revoked")


def test_revoked_jtis_reads_the_table(db):
    user = auth_service.create_user(db, email="sock-table@x.com", password=PASSWORD)
    live_token, _ = auth_service.create_access_token(user.id, db=db)
    gone_token, _ = auth_service.create_access_token(user.id, db=db)
    auth_service.revoke_session(db, _jti(gone_token), user.id)
    assert auth_service.revoked_jtis(db, [_jti(live_token), _jti(gone_token), "no-such-row"]) == {_jti(gone_token)}
    assert db.query(SessionRow).count() == 2


# ---------------------------------------------------------------------------
# T-5.5.8: X-Forwarded-For counts only from a trusted proxy
# ---------------------------------------------------------------------------


def _request(peer: str | None, *lines: str) -> Request:
    headers = [(b"x-forwarded-for", line.encode("latin-1")) for line in lines]
    return Request({"type": "http", "headers": headers, "client": (peer, 40000) if peer is not None else None})


@pytest.fixture
def behind_proxy(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.1, 172.16.0.0/12, 2001:db8::/32")


def test_with_no_proxies_the_header_is_ignored():
    assert client_ip(_request("203.0.113.9", "198.51.100.7")) == "203.0.113.9"


def test_no_peer_is_none():
    assert client_ip(_request(None, "198.51.100.7")) is None


def test_an_untrusted_peer_cannot_use_the_header(behind_proxy):
    assert client_ip(_request("203.0.113.9", "198.51.100.7")) == "203.0.113.9"


def test_a_trusted_peer_gives_the_nearest_untrusted_hop(behind_proxy):
    assert client_ip(_request("10.0.0.1", "198.51.100.7")) == "198.51.100.7"
    # Two of our own proxies in the path, one named by a CIDR.
    assert client_ip(_request("10.0.0.1", "198.51.100.7, 172.16.3.4")) == "198.51.100.7"


def test_a_client_cannot_spoof_past_the_proxy(behind_proxy):
    """What the client wrote is on the left; the proxy appended the rest."""
    assert client_ip(_request("10.0.0.1", "1.2.3.4, 198.51.100.7")) == "198.51.100.7"
    assert client_ip(_request("10.0.0.1", "10.0.0.1, 198.51.100.7")) == "198.51.100.7"


def test_garbage_the_client_wrote_does_not_matter(behind_proxy):
    """The walk stops at the first untrusted address, before reaching it."""
    assert client_ip(_request("10.0.0.1", "not-an-ip, 198.51.100.7")) == "198.51.100.7"


def test_a_proxy_that_adds_its_own_line_is_read(behind_proxy):
    """The client's own line comes first, so reading one line would take it."""
    assert client_ip(_request("10.0.0.1", "1.2.3.4", "198.51.100.7")) == "198.51.100.7"


def test_a_request_from_inside_is_the_peer(behind_proxy):
    assert client_ip(_request("10.0.0.1", "172.16.3.4")) == "10.0.0.1"


@pytest.mark.parametrize(
    "header",
    [
        "",
        " ",
        "not-an-ip",
        "198.51.100.7, not-an-ip",
        "198.51.100.7,",
        "<script>",
        ", ,",
        # T-5.5.9: the shapes that look like an address with a port and are not.
        "198.51.100.7:99999",
        "198.51.100.7:",
        "198.51.100.7:http",
        "198.51.100.7:443:443",
        "[2606:4700::1111]:99999",
        "[2606:4700::1111]:",
        "[198.51.100.7]",
        "[198.51.100.7]:443",
        "[not-an-ip]:443",
        "[2606:4700::1111",
    ],
)
def test_a_malformed_header_falls_back_to_the_peer(behind_proxy, header):
    assert client_ip(_request("10.0.0.1", header)) == "10.0.0.1"


def test_a_missing_header_falls_back_to_the_peer(behind_proxy):
    assert client_ip(_request("10.0.0.1")) == "10.0.0.1"


@pytest.mark.parametrize("peer", ["testclient", "unix:/run/app.sock", ""])
def test_a_malformed_peer_is_the_peer(behind_proxy, peer):
    assert client_ip(_request(peer, "198.51.100.7")) == peer


def test_ipv6_proxies_and_clients(behind_proxy):
    assert client_ip(_request("2001:db8::1", "2606:4700::1111")) == "2606:4700::1111"
    assert client_ip(_request("2606:4700::1111", "198.51.100.7")) == "2606:4700::1111"


def test_a_dual_stack_listener_reports_an_ipv4_proxy_as_ipv6(behind_proxy):
    assert client_ip(_request("::ffff:10.0.0.1", "198.51.100.7")) == "198.51.100.7"
    assert client_ip(_request("10.0.0.1", "::ffff:198.51.100.7")) == "198.51.100.7"


@pytest.mark.parametrize(
    "header, expected",
    [
        ("198.51.100.7:5678", "198.51.100.7"),
        ("[2606:4700::1111]:443", "2606:4700::1111"),
        ("[2606:4700::1111]", "2606:4700::1111"),
        ("198.51.100.7:0", "198.51.100.7"),
        ("198.51.100.7:65535", "198.51.100.7"),
        ("[::ffff:198.51.100.7]:443", "198.51.100.7"),
        (" 198.51.100.7:5678 ", "198.51.100.7"),
        # A bare IPv6 address is not address-and-port, however it ends.
        ("2606:4700::1111:443", "2606:4700::1111:443"),
        ("1.2.3.4, 198.51.100.7:5678", "198.51.100.7"),
        # Our own proxy, with its port, is still our own proxy.
        ("198.51.100.7, 10.0.0.1:8080", "198.51.100.7"),
        ("198.51.100.7, [2001:db8::5]:443", "198.51.100.7"),
    ],
)
def test_a_proxy_that_appends_a_port_is_read(behind_proxy, header, expected):
    """T-5.5.9: it used to read as malformed, so the caller became the proxy
    and every user shared one bucket."""
    assert client_ip(_request("10.0.0.1", header)) == expected


@pytest.mark.parametrize(
    "ip, bucket",
    [
        ("2606:4700:1:2:3:4:5:6", "2606:4700:1:2::/64"),
        ("2606:4700:1:2:ffff:ffff:ffff:ffff", "2606:4700:1:2::/64"),
        ("2606:4700:1:3::1", "2606:4700:1:3::/64"),
        ("::1", "::/64"),
        ("fe80::1%eth0", "fe80::/64"),
        # IPv4 keeps its own address, however the listener spelt it.
        ("198.51.100.7", "198.51.100.7"),
        ("::ffff:198.51.100.7", "198.51.100.7"),
        # Not addresses: whatever was asked about is its own bucket.
        ("testclient", "testclient"),
        ("unknown", "unknown"),
    ],
)
def test_the_rate_limit_bucket(ip, bucket):
    assert rate_limit_bucket(ip) == bucket


def test_a_bad_entry_in_the_setting_is_logged_and_skipped(monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(client_ip_module, "logger", log)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "not-a-network-b5, 10.0.0.1")
    client_ip_module._parse_networks.cache_clear()
    assert client_ip(_request("10.0.0.1", "198.51.100.7")) == "198.51.100.7"
    log.warning.assert_called_once()
    client_ip_module._parse_networks.cache_clear()


def _from(peer: str) -> TestClient:
    return TestClient(app, client=(peer, 40000))


@pytest.fixture
def limited(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_MIN", 3)
    # One clock minute, as in test_rate_limit.py: the limiter buckets by the
    # minute, so requests that straddle one would see their count reset.
    monkeypatch.setattr(rate_limit_service, "_now", lambda: 1_000_020)
    rate_limit_service.reset()
    yield
    rate_limit_service.reset()


def _try_login(client, forwarded: str | None = None) -> int:
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    return client.post(LOGIN, json={"email": "limit@x.com", "password": "wrong-password"}, headers=headers).status_code


def test_a_new_header_each_time_does_not_escape_the_limit(unauthenticated_client, limited):
    """#399's end-to-end run got past the limit exactly this way."""
    client = _from("203.0.113.9")
    statuses = [_try_login(client, f"198.51.100.{i}") for i in range(5)]
    assert statuses == [401, 401, 401, 429, 429]


def test_behind_a_proxy_the_limit_is_each_clients_own(unauthenticated_client, limited, behind_proxy):
    proxy = _from("10.0.0.1")
    statuses = [_try_login(proxy, f"1.2.3.{i}, 198.51.100.7") for i in range(5)]
    assert statuses == [401, 401, 401, 429, 429], "a spoofed left side must not escape"
    assert _try_login(proxy, "198.51.100.8") == 401, "another client has its own bucket"


def test_behind_a_proxy_with_it_unset_everyone_shares_one_bucket(unauthenticated_client, limited):
    """The failure the deployment docs warn about."""
    proxy = _from("10.0.0.1")
    statuses = [_try_login(proxy, f"198.51.100.{i}") for i in range(5)]
    assert statuses == [401, 401, 401, 429, 429]


def test_a_whole_ipv6_64_shares_one_bucket(unauthenticated_client, limited, behind_proxy):
    """T-5.5.9: an address per request from one customer's /64 is no escape."""
    proxy = _from("10.0.0.1")
    statuses = [_try_login(proxy, f"2606:4700:1:2::{i}") for i in range(1, 6)]
    assert statuses == [401, 401, 401, 429, 429]
    assert _try_login(proxy, "2606:4700:1:3::1") == 401, "the next /64 is someone else"


def test_an_ipv6_peer_is_bucketed_by_its_64_too(unauthenticated_client, limited):
    statuses = [_try_login(_from(f"2606:4700:1:2::{i}")) for i in range(1, 6)]
    assert statuses == [401, 401, 401, 429, 429]


def test_ipv4_callers_are_still_each_their_own(unauthenticated_client, limited):
    statuses = [_try_login(_from(f"198.51.100.{i}")) for i in range(1, 6)]
    assert statuses == [401] * 5


def test_a_proxy_that_appends_a_port_keeps_clients_apart(unauthenticated_client, limited, behind_proxy):
    """T-5.5.9, end to end: every client used to read as the proxy."""
    proxy = _from("10.0.0.1")
    statuses = [_try_login(proxy, f"198.51.100.{i}:5678") for i in range(1, 6)]
    assert statuses == [401] * 5


def test_the_full_ipv6_address_is_what_gets_written_down(unauthenticated_client, db, behind_proxy):
    """T-5.5.9: the /64 is the limiter's alone. The audit log and the session
    list keep the address, without the port."""
    auth_service.create_user(db, email="ip-six@x.com", password=PASSWORD)
    body = {"email": "ip-six@x.com", "password": PASSWORD}
    r = _from("10.0.0.1").post(LOGIN, json=body, headers={"X-Forwarded-For": "[2606:4700:1:2:3:4:5:6]:443"})
    assert r.status_code == 200
    db.expire_all()
    assert db.query(SessionRow).one().ip_address == "2606:4700:1:2:3:4:5:6"
    audit = db.query(AuditLog).filter(AuditLog.event == Event.LOGIN_SUCCESS.value).one()
    assert audit.ip_address == "2606:4700:1:2:3:4:5:6"


def test_the_audit_log_and_the_session_row_use_the_same_address(unauthenticated_client, db, monkeypatch):
    auth_service.create_user(db, email="ip-ok@x.com", password=PASSWORD)
    body = {"email": "ip-ok@x.com", "password": PASSWORD}

    # Unset: a caller's own header changes nothing.
    r = _from("203.0.113.9").post(LOGIN, json=body, headers={"X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 200
    db.expire_all()
    assert db.query(SessionRow).one().ip_address == "203.0.113.9"
    assert db.query(AuditLog).filter(AuditLog.event == Event.LOGIN_SUCCESS.value).one().ip_address == "203.0.113.9"

    # Behind a named proxy: the client.
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.1")
    r = _from("10.0.0.1").post(LOGIN, json=body, headers={"X-Forwarded-For": "1.2.3.4, 198.51.100.7"})
    assert r.status_code == 200
    db.expire_all()
    newest = db.query(SessionRow).order_by(SessionRow.created_at.desc()).first()
    assert newest.ip_address == "198.51.100.7"
    assert {a.ip_address for a in db.query(AuditLog).filter(AuditLog.event == Event.LOGIN_SUCCESS.value)} == {
        "203.0.113.9",
        "198.51.100.7",
    }


def test_the_second_factor_session_row_uses_it_too(unauthenticated_client, db, stable_key, monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.1")
    _user, secret, _codes = _mfa_user(db, "ip-mfa@x.com")
    proxy = _from("10.0.0.1")
    ticket = _ticket(proxy, "ip-mfa@x.com")
    r = proxy.post(
        LOGIN_MFA,
        json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()},
        headers={"X-Forwarded-For": "198.51.100.7"},
    )
    assert r.status_code == 200
    db.expire_all()
    assert db.query(SessionRow).one().ip_address == "198.51.100.7"


def test_nothing_else_reads_the_header():
    """Every reader goes through ``client_ip``, so the rule has one home."""
    root = Path(__file__).resolve().parents[2] / "app"
    readers = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if any(s in p.read_text(encoding="utf-8").lower() for s in ('"x-forwarded-for"', '"forwarded"'))
    ]
    assert readers == ["utils/client_ip.py"]
    peers = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if "request.client" in p.read_text(encoding="utf-8")
    ]
    assert peers == [], "the socket peer is read in client_ip alone"


def test_the_launchers_turn_uvicorns_own_proxy_handling_off():
    """By default uvicorn rewrites the peer from the header for callers at
    127.0.0.1, before this app runs, which would undo the rule above."""
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    for name in ("start.ps1", "restart_services.ps1"):
        assert "'--no-proxy-headers'" in (scripts / name).read_text(encoding="utf-8"), name


# ---------------------------------------------------------------------------
# T-5.6.10: clarify is served on the asker's key
# ---------------------------------------------------------------------------

OWN_KEY = "own-key-placeholder"


@pytest.fixture
def keys_used(monkeypatch, metered_llms):
    """The key each client was built with, below ``get_llm_for``, so the
    production lookup runs. None is the install's key."""
    seen: list[str | None] = []

    def _build(cfg, temperature, max_tokens, *, byok_api_key=None):
        seen.append(byok_api_key)
        return metered_llms(cfg, temperature, max_tokens, byok_api_key=byok_api_key)

    monkeypatch.setattr(llm_service, "_build_from_config", _build)
    metered_llms.reply = CLARIFY_JSON
    return seen


def _completed_job(db, tenant_id):
    job = Job(job_type="topic", topic="tariffs", status="completed", num_videos=1, tenant_id=tenant_id)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _clarify(client, db, user, surface):
    if surface == "job":
        path = f"/api/v1/jobs/{_completed_job(db, user.id).id}/qa/clarify"
    else:
        path = "/api/v1/library/qa/clarify"
    return client.post(path, json={"question": "who pays?"})


def _store_key(db, user, tier, use_case):
    user.tier = tier
    db.commit()
    provider = resolve_config(use_case).provider
    assert provider in byok_service.RESOLVED_PROVIDERS
    byok_service.set_credential(db, user.id, provider, OWN_KEY)


CLARIFY_SURFACES = [("job", "qa_clarification"), ("library", "library_qa_clarification")]


@pytest.mark.parametrize("surface, use_case", CLARIFY_SURFACES)
def test_clarify_is_served_on_the_askers_own_key(client, db, test_user, stable_key, keys_used, surface, use_case):
    _store_key(db, test_user, "studio", use_case)
    r = _clarify(client, db, test_user, surface)
    assert r.status_code == 200, r.text
    assert r.json()["interpretation"] == "you mean X"
    assert keys_used == [OWN_KEY]


@pytest.mark.parametrize("surface, use_case", CLARIFY_SURFACES)
def test_a_tier_without_byok_uses_the_install_key(client, db, test_user, stable_key, keys_used, surface, use_case):
    _store_key(db, test_user, "free", use_case)
    assert _clarify(client, db, test_user, surface).status_code == 200
    assert keys_used == [None]


@pytest.mark.parametrize("surface, use_case", CLARIFY_SURFACES)
def test_a_key_that_cannot_be_read_falls_back_as_on_the_ask_route(
    client, db, test_user, stable_key, keys_used, monkeypatch, surface, use_case
):
    _store_key(db, test_user, "studio", use_case)
    _rotate_the_key(monkeypatch)
    assert _clarify(client, db, test_user, surface).status_code == 200
    assert keys_used == [None]


class _ProviderRefused(RuntimeError):
    pass


@pytest.mark.parametrize("surface, use_case", CLARIFY_SURFACES)
def test_a_key_the_provider_refuses_fails_as_on_the_ask_route(
    client, db, test_user, stable_key, keys_used, monkeypatch, surface, use_case
):
    """The ask route neither retries nor falls back to the install's key: the
    user's key is theirs to fix. So the provider's refusal is not swallowed,
    and no second client is built."""
    _store_key(db, test_user, "studio", use_case)

    class _Refusing(MeteredFakeChat):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise _ProviderRefused("401 from the provider")

    def _build(cfg, temperature, max_tokens, *, byok_api_key=None):
        keys_used.append(byok_api_key)
        return _Refusing()

    monkeypatch.setattr(llm_service, "_build_from_config", _build)
    with pytest.raises(_ProviderRefused):
        _clarify(client, db, test_user, surface)
    assert keys_used == [OWN_KEY]


@pytest.mark.parametrize("surface, use_case", CLARIFY_SURFACES)
def test_clarify_honours_the_askers_model_pin_and_its_reply_shape(
    client, db, test_user, stable_key, monkeypatch, surface, use_case
):
    """``byok_context`` also loads the per-user model pins, so clarify can now
    reach a model that answers with thinking blocks. The old ``.content``
    read would crash on the list."""
    db.add(UserLLMOverride(user_id=test_user.id, use_case=use_case, provider="anthropic", model="claude-pin", reasoning="off"))
    db.commit()
    built: list[str] = []

    class _Thinking(MeteredFakeChat):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            content = [{"type": "thinking", "thinking": "hm"}, {"type": "text", "text": CLARIFY_JSON}]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    def _build(cfg, temperature, max_tokens, *, byok_api_key=None):
        built.append(cfg.model)
        return _Thinking()

    monkeypatch.setattr(llm_service, "_build_from_config", _build)
    r = _clarify(client, db, test_user, surface)
    assert r.status_code == 200, r.text
    assert r.json()["clarifications"] == ["a?", "b?", "c?"]
    assert built == ["claude-pin"]


@pytest.mark.parametrize("surface, use_case", CLARIFY_SURFACES)
@pytest.mark.parametrize(
    "provider, model, reasoning, thinking",
    [
        # A measured ceiling, far above the budget.
        ("anthropic", "claude-haiku-4-5", "medium", 4_096),
        # Unmeasured, so `max_output_for` says 4,096: clamping to that leaves
        # `max_tokens` equal to the budget, or under it, and Claude refuses both.
        ("anthropic", "claude-opus-4-5", "medium", 4_096),
        ("anthropic", "claude-opus-4-5", "high", 16_384),
        # No budget is sent to OpenAI, but a low cap can come back empty.
        ("openai", "gpt-5.4", "medium", 4_096),
    ],
)
def test_clarify_leaves_room_for_the_reply_above_a_pins_thinking(
    client, db, test_user, stable_key, monkeypatch, metered_llms, surface, use_case, provider, model, reasoning, thinking
):
    """A pin reaches both clarify routes now, and thinking counts inside
    ``max_tokens``, so a bare 400 is refused or comes back empty. Clarify is
    awaited with no catch, so that would stop the Ask button itself.
    ``claude-opus-4-5`` is the pin CLAUDE.md's own example names."""
    db.add(UserLLMOverride(user_id=test_user.id, use_case=use_case, provider=provider, model=model, reasoning=reasoning))
    db.commit()
    caps: list[int] = []

    def _build(cfg, temperature, max_tokens, *, byok_api_key=None):
        caps.append(max_tokens)
        return metered_llms(cfg, temperature, max_tokens, byok_api_key=byok_api_key)

    monkeypatch.setattr(llm_service, "_build_from_config", _build)
    metered_llms.reply = CLARIFY_JSON
    r = _clarify(client, db, test_user, surface)
    assert r.status_code == 200, r.text
    assert caps == [thinking + 400]


@pytest.mark.parametrize("surface, use_case", CLARIFY_SURFACES)
def test_clarify_with_reasoning_off_keeps_its_cap(
    client, db, test_user, stable_key, monkeypatch, metered_llms, surface, use_case
):
    db.add(UserLLMOverride(user_id=test_user.id, use_case=use_case, provider="anthropic", model="claude-opus-4-5", reasoning="off"))
    db.commit()
    caps: list[int] = []

    def _build(cfg, temperature, max_tokens, *, byok_api_key=None):
        caps.append(max_tokens)
        return metered_llms(cfg, temperature, max_tokens, byok_api_key=byok_api_key)

    monkeypatch.setattr(llm_service, "_build_from_config", _build)
    metered_llms.reply = CLARIFY_JSON
    assert _clarify(client, db, test_user, surface).status_code == 200
    assert caps == [400]


def test_a_ceiling_above_the_thinking_still_caps_the_reply(monkeypatch):
    """A ceiling is only ignored when nothing could ever run under it."""
    cfg = UseCaseConfig(provider="anthropic", model="claude-measured", reasoning="medium")
    monkeypatch.setattr(llm_service, "max_output_for", lambda _model: 4_200)
    assert llm_service.max_tokens_for_reply(cfg, 400) == 4_200


def test_a_shelf_question_is_served_on_the_askers_own_key(client, db, test_user, stable_key, keys_used):
    """The shelf's ask route shares the library's core, and the page asks the
    library's clarify (``POST /library/qa/clarify`` takes no scope), so the
    two tests above cover its clarify."""
    _store_key(db, test_user, "studio", "library_qa_formulate_answer")
    shelf = shelf_service.create_shelf(db, test_user.id, "Rates")

    def _agent(**_kwargs):
        call_llm("library_qa_formulate_answer")
        return {"answer": "An answer.", "references": []}

    with (
        patch("app.agents.qa_agent.run_library_qa_agent", side_effect=_agent),
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        r = client.post(f"/api/v1/shelves/{shelf.id}/qa", json={"question": "What about rates?"})
    assert r.status_code == 200, r.text
    assert keys_used == [OWN_KEY]


# ---------------------------------------------------------------------------
# T-5.6.11: a rotated key is reported, not read as a wrong code
# ---------------------------------------------------------------------------


def _says_the_secret_cannot_be_read(r, what: str) -> None:
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert detail.startswith(what)
    assert "stored secret cannot be read" in detail
    assert "BYOK_ENCRYPTION_KEY" in detail
    assert "operator" in detail


def test_a_rotated_key_reads_as_the_key_not_a_wrong_code(unauthenticated_client, db, stable_key, monkeypatch):
    _user, secret, codes = _mfa_user(db, "rot-login@x.com")
    new_key = _rotate_the_key(monkeypatch)
    ticket = _ticket(unauthenticated_client, "rot-login@x.com")

    r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()})

    _says_the_secret_cannot_be_read(r, "The authenticator code cannot be checked")
    assert "recovery code still works" in r.json()["detail"]
    assert secret not in r.text and new_key not in r.text
    # Recovery codes are hashed, not encrypted: they still sign in.
    assert unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": codes[0]}).status_code == 200


def test_turning_off_with_a_rotated_key(unauthenticated_client, db, stable_key, monkeypatch):
    user, secret, codes = _mfa_user(db, "rot-off@x.com")
    token = _session(db, user)
    _rotate_the_key(monkeypatch)

    r = _turn_off(unauthenticated_client, token, pyotp.TOTP(secret).now())
    _says_the_secret_cannot_be_read(r, "The code cannot be checked")
    assert mfa_service.is_enabled(db, user.id) is True

    assert _turn_off(unauthenticated_client, token, codes[0]).status_code == 200
    assert mfa_service.is_enabled(db, user.id) is False


# What a mistyped or a guessed recovery code looks like: its length, no match.
A_RECOVERY_GUESS = "ABCDEF0123"


@pytest.mark.parametrize("break_key", [_rotate_the_key, _break_the_key], ids=["rotated", "malformed"])
def test_a_code_the_key_cannot_check_leaves_recovery_codes_reachable(
    unauthenticated_client, db, stable_key, monkeypatch, break_key
):
    """The 503 says a recovery code still works, and someone retrying during
    an outage will send it many times. An authenticator code tested nothing
    here, so it spends nothing, and the recovery code is still let in."""
    user, secret, codes = _mfa_user(db, "rot-retry@x.com")
    token = _session(db, user)
    break_key(monkeypatch)

    for _ in range(mfa_service.MFA_TICKET_MAX_ATTEMPTS + 2):
        r = _turn_off(unauthenticated_client, token, pyotp.TOTP(secret).now())
        assert r.status_code == 503, r.text
        assert "recovery code still works" in r.json()["detail"]

    assert _turn_off(unauthenticated_client, token, codes[0]).status_code == 200
    assert mfa_service.is_enabled(db, user.id) is False


def test_recovery_guesses_stay_counted_while_the_key_is_broken(unauthenticated_client, db, stable_key, monkeypatch):
    """A code that could be a recovery code WAS checked against the stored
    hashes, so a broken key is no way round the cap. The fifth says so at
    once: a 503 there would promise a recovery code the next try refuses."""
    user, _secret, codes = _mfa_user(db, "rot-guess@x.com")
    token = _session(db, user)
    _rotate_the_key(monkeypatch)

    for _ in range(mfa_service.MFA_TICKET_MAX_ATTEMPTS - 1):
        assert _turn_off(unauthenticated_client, token, A_RECOVERY_GUESS).status_code == 503
    r = _turn_off(unauthenticated_client, token, A_RECOVERY_GUESS)
    assert r.status_code == 429 and r.json()["detail"] == mfa_router.DISABLE_EXHAUSTED_DETAIL

    # Past the cap nothing is checked, a real recovery code included.
    assert _turn_off(unauthenticated_client, token, codes[0]).status_code == 429
    assert mfa_service.is_enabled(db, user.id) is True
    db.expire_all()
    stored = json.loads(db.query(MfaSecret).filter(MfaSecret.user_id == user.id).one().recovery_codes_json)
    assert len(stored) == mfa_service.RECOVERY_CODE_COUNT, "the refused code was not spent"
    # A refused guess is on the record, as with a working key.
    rows = _events(db, Event.MFA_DISABLE_FAILED, user.id)
    assert len(rows) == mfa_service.MFA_TICKET_MAX_ATTEMPTS
    assert _meta(rows[-1])["reason"] == "too_many_attempts"


def test_a_code_that_was_not_checked_keeps_the_misses_before_it(unauthenticated_client, db, stable_key, monkeypatch):
    """It gives back its own attempt, never the count: retrying through a
    broken key must not wipe real misses."""
    user, secret, _codes = _mfa_user(db, "rot-keep@x.com")
    token = _session(db, user)
    for _ in range(2):
        assert _turn_off(unauthenticated_client, token, _wrong_code(secret)).status_code == 400
    _rotate_the_key(monkeypatch)

    assert _turn_off(unauthenticated_client, token, pyotp.TOTP(secret).now()).status_code == 503
    db.expire_all()
    assert db.query(MfaStepTicket).one().attempts == 2


def test_only_a_recovery_codes_length_can_be_one():
    assert mfa_service.could_be_recovery_code("123456") is False
    assert mfa_service.could_be_recovery_code(" 123456 ") is False
    assert mfa_service.could_be_recovery_code(A_RECOVERY_GUESS) is True
    assert mfa_service.could_be_recovery_code(f" {A_RECOVERY_GUESS.lower()} ") is True, "as `_hash_code` reads it"
    assert all(mfa_service.could_be_recovery_code(c) for c in mfa_service._generate_recovery_codes())


def test_only_the_code_that_checked_nothing_is_handed_back(unauthenticated_client, db, stable_key, monkeypatch):
    user, secret, _codes = _mfa_user(db, "rot-mixed@x.com")
    token = _session(db, user)
    _rotate_the_key(monkeypatch)

    assert _turn_off(unauthenticated_client, token, pyotp.TOTP(secret).now()).status_code == 503
    assert _turn_off(unauthenticated_client, token, A_RECOVERY_GUESS).status_code == 503
    assert _turn_off(unauthenticated_client, token, pyotp.TOTP(secret).now()).status_code == 503

    db.expire_all()
    assert db.query(MfaStepTicket).one().attempts == 1


def test_a_closed_window_is_a_429_with_a_broken_key_too(unauthenticated_client, db, stable_key, monkeypatch):
    """Past the cap a 503 would send the user to a recovery code that this
    route is about to refuse."""
    user, secret, _codes = _mfa_user(db, "rot-closed@x.com")
    token = _session(db, user)
    for _ in range(mfa_service.MFA_TICKET_MAX_ATTEMPTS):
        _turn_off(unauthenticated_client, token, _wrong_code(secret))
    _rotate_the_key(monkeypatch)
    r = _turn_off(unauthenticated_client, token, pyotp.TOTP(secret).now())
    assert r.status_code == 429 and r.json()["detail"] == mfa_router.DISABLE_EXHAUSTED_DETAIL


def test_the_shape_check_reads_what_the_hash_reads():
    """U+FB00 upper-cases to "FF", so the hash reads this as ten hex characters
    and a recovery code can match it. Judged on the raw text it would be handed
    back after a real recovery check: an uncounted guess."""
    ligature = "\ufb00" + "0" * 8
    assert mfa_service._hash_code(ligature) == mfa_service._hash_code("FF" + "0" * 8)
    assert mfa_service.could_be_recovery_code(ligature) is True
    for code in ("123 456", "12345678", "ABCDEF012G", "ABCDEF01234"):
        assert mfa_service.could_be_recovery_code(code) is False, code


def test_confirming_setup_with_a_rotated_key(unauthenticated_client, db, stable_key, monkeypatch):
    user = auth_service.create_user(db, email="rot-enrol@x.com", password=PASSWORD)
    secret, _uri = mfa_service.enroll(db, user)
    token = _session(db, user)
    _rotate_the_key(monkeypatch)

    r = unauthenticated_client.post(
        f"{MFA}/verify-enrollment", json={"code": pyotp.TOTP(secret).now()}, headers=_auth(token)
    )
    _says_the_secret_cannot_be_read(r, "Two-step verification cannot be turned on")


def test_an_unset_key_after_a_restart_reads_the_same(unauthenticated_client, db, stable_key, monkeypatch):
    """Unset, each process generates its own key, so a restart is a rotation."""
    _user, secret, _codes = _mfa_user(db, "rot-unset@x.com")
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", None)
    byok_service._get_fernet.cache_clear()
    ticket = _ticket(unauthenticated_client, "rot-unset@x.com")
    r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()})
    _says_the_secret_cannot_be_read(r, "The authenticator code cannot be checked")


def test_a_corrupt_row_reads_the_same(unauthenticated_client, db, stable_key):
    user, secret, _codes = _mfa_user(db, "rot-corrupt@x.com")
    db.query(MfaSecret).filter(MfaSecret.user_id == user.id).update({MfaSecret.secret_encrypted: "not-a-fernet-token"})
    db.commit()
    ticket = _ticket(unauthenticated_client, "rot-corrupt@x.com")
    r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()})
    _says_the_secret_cannot_be_read(r, "The authenticator code cannot be checked")


def test_neither_the_secret_nor_the_key_reaches_a_log(unauthenticated_client, db, stable_key, monkeypatch):
    service_log, router_log = MagicMock(), MagicMock()
    monkeypatch.setattr(mfa_service, "logger", service_log)
    monkeypatch.setattr(mfa_router, "logger", router_log)
    user, secret, _codes = _mfa_user(db, "rot-log@x.com")
    old_key = settings.BYOK_ENCRYPTION_KEY
    new_key = _rotate_the_key(monkeypatch)
    ticket = _ticket(unauthenticated_client, "rot-log@x.com")

    r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()})

    assert r.status_code == 503
    written = repr(service_log.mock_calls) + repr(router_log.mock_calls)
    assert user.id in written, "the operator can see whose secret it is"
    for value in (secret, old_key, new_key):
        assert value not in written
    service_log.exception.assert_not_called()


def test_a_wrong_code_is_still_a_wrong_code_when_the_key_is_fine(unauthenticated_client, db, stable_key):
    _user, secret, _codes = _mfa_user(db, "rot-fine@x.com")
    ticket = _ticket(unauthenticated_client, "rot-fine@x.com")
    r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": _wrong_code(secret)})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid TOTP or recovery code"


def test_mutation_swallowing_invalid_token_reads_as_a_wrong_code(unauthenticated_client, db, stable_key, monkeypatch):
    def _swallowing(row, code):
        try:
            secret = byok_service.decrypt_secret(row.secret_encrypted)
        except byok_service.EncryptionConfigurationError:
            raise
        except Exception:
            return False
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)

    monkeypatch.setattr(mfa_service, "_verify_totp_against_row", _swallowing)
    _user, secret, _codes = _mfa_user(db, "rot-mut@x.com")
    _rotate_the_key(monkeypatch)
    ticket = _ticket(unauthenticated_client, "rot-mut@x.com")
    r = unauthenticated_client.post(LOGIN_MFA, json={"mfa_token": ticket, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 401


def test_the_app_handler_tells_the_two_failures_apart(unauthenticated_client):
    """The net for a route that does not catch the error itself."""

    def _reads():
        raise byok_service.StoredSecretUnreadableError("placeholder")

    app.add_api_route("/api/v1/__t5611_reads", _reads, methods=["GET"])
    try:
        r = unauthenticated_client.get("/api/v1/__t5611_reads")
    finally:
        app.router.routes[:] = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/api/v1/__t5611_reads"]
    _says_the_secret_cannot_be_read(r, "Nothing stored encrypted can be saved or read")
