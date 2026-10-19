"""T-5.4.9 — the JWT library swap must keep the algorithm list pinned.

python-jose was replaced by PyJWT. The behaviour that matters for security is
that `decode_token` accepts only tokens signed with the configured algorithm
and secret: an `alg: none` token, a token signed with another HMAC variant,
and a token signed with another secret must all be rejected, while a token
issued by `create_access_token` round-trips with its `jti`.
"""
from __future__ import annotations

import base64
import json

import jwt

from app.config import settings
from app.services import auth_service, mfa_service


def _b64(obj: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def test_issued_token_round_trips_with_jti():
    token, expires_in = auth_service.create_access_token("user-1")
    assert isinstance(token, str) and expires_in > 0
    payload = auth_service.decode_token(token)
    assert payload is not None
    assert payload["sub"] == "user-1"
    assert len(payload["jti"]) == 36


def test_alg_none_token_is_rejected():
    header = _b64({"alg": "none", "typ": "JWT"})
    body = _b64({"sub": "user-1", "exp": 4102444800})
    assert auth_service.decode_token(f"{header}.{body}.") is None


def test_other_hmac_variant_is_rejected():
    other = "HS512" if settings.JWT_ALGORITHM != "HS512" else "HS384"
    token = jwt.encode({"sub": "user-1", "exp": 4102444800}, settings.JWT_SECRET, algorithm=other)
    assert auth_service.decode_token(token) is None


def test_wrong_secret_is_rejected():
    token = jwt.encode({"sub": "user-1", "exp": 4102444800}, "not-the-secret", algorithm=settings.JWT_ALGORITHM)
    assert auth_service.decode_token(token) is None


def test_expired_token_is_rejected():
    token = jwt.encode({"sub": "user-1", "exp": 1}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    assert auth_service.decode_token(token) is None


def test_mfa_step_token_round_trips_and_is_not_an_access_token():
    token = mfa_service.issue_mfa_step_token("user-2")
    assert mfa_service.decode_mfa_step_token(token) == "user-2"
    # An ordinary access token must not pass as an MFA-step token.
    access, _ = auth_service.create_access_token("user-2")
    assert mfa_service.decode_mfa_step_token(access) is None
