"""A blank JWT_SECRET must never become an empty HMAC key (T-5.4.9).

Found when PyJWT replaced python-jose: the dev .env had ``JWT_SECRET=`` and
jose had been signing every token with an empty key. The validator maps blank
to the development default and warns; a real value passes through untouched.
The warning waits for ``configure_logging`` (T-4.11.3.2), since settings load
before logging has a format.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import Settings, held_warnings
from app.utils.json_logging import configure_logging


@pytest.fixture(autouse=True)
def _nothing_held():
    """Another test can load settings from a blank template and leave its
    warning held (test_docs_match_code does); only a migration says it."""
    held_warnings.clear()
    yield
    held_warnings.clear()


def test_blank_secret_falls_back_to_dev_default_and_warns():
    with patch("logging.Logger.warning") as warn:
        s = Settings(JWT_SECRET="   ")
        assert not warn.called, "held until logging has its format"
        configure_logging()
        assert s.JWT_SECRET == "dev-insecure-secret-change-me-in-production"
        assert warn.call_count == 1
        assert "JWT_SECRET is blank" in warn.call_args.args[0]
        configure_logging()
    assert warn.call_count == 1, "said once, however often logging is set up"


def test_settings_loaded_twice_warn_once():
    """A script or Alembic can load settings again before logging is set up."""
    with patch("logging.Logger.warning") as warn:
        Settings(JWT_SECRET="")
        Settings(JWT_SECRET="   ")
        configure_logging()
    assert warn.call_count == 1


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
