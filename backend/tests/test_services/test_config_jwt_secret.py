"""A blank JWT_SECRET must never become an empty HMAC key (T-5.4.9).

Found when PyJWT replaced python-jose: the dev .env had ``JWT_SECRET=`` and
jose had been signing every token with an empty key. The validator maps blank
to the development default and warns; a real value passes through untouched.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

from app.config import Settings


def test_blank_secret_falls_back_to_dev_default_and_warns():
    with patch("logging.Logger.warning") as warn:
        s = Settings(JWT_SECRET="   ")
    assert s.JWT_SECRET == "dev-insecure-secret-change-me-in-production"
    assert warn.called
    assert "JWT_SECRET is blank" in warn.call_args.args[0]


def test_real_secret_passes_through():
    s = Settings(JWT_SECRET="a-long-random-value-0123456789")
    assert s.JWT_SECRET == "a-long-random-value-0123456789"


def test_tokens_sign_with_a_non_empty_key():
    # Whatever .env says, the running settings must yield a usable key.
    from app.config import settings
    from app.services import auth_service

    assert settings.JWT_SECRET.strip()
    token, _ = auth_service.create_access_token("user-x")
    assert auth_service.decode_token(token)["sub"] == "user-x"
