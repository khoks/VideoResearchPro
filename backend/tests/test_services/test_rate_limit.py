"""Tests for E-5.5 rate limiting.

The rate-limiter is in-memory (one process = one bucket-set), which
makes deterministic testing easy. Each test starts with a clean
bucket via the auto-reset in `conftest.py::db`.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services import rate_limit_service
from app.services.rate_limit_service import RateLimit, check_and_consume


# ---------------------------------------------------------------------------
# RateLimit dataclass
# ---------------------------------------------------------------------------


def test_rate_limit_rejects_invalid_values():
    with pytest.raises(ValueError):
        RateLimit(requests=0)
    with pytest.raises(ValueError):
        RateLimit(requests=-1)
    with pytest.raises(ValueError):
        RateLimit(requests=10, window_sec=0)


# ---------------------------------------------------------------------------
# check_and_consume
# ---------------------------------------------------------------------------


def test_first_call_under_limit_is_allowed():
    rate_limit_service.reset()
    allowed, count, retry = check_and_consume("k", RateLimit(requests=3))
    assert allowed
    assert count == 1
    assert retry == 0


def test_consecutive_calls_increment_until_limit():
    rate_limit_service.reset()
    lim = RateLimit(requests=3)

    a1, c1, _ = check_and_consume("k", lim, now=100)
    a2, c2, _ = check_and_consume("k", lim, now=100)
    a3, c3, _ = check_and_consume("k", lim, now=100)
    a4, c4, retry = check_and_consume("k", lim, now=100)

    assert (a1, a2, a3) == (True, True, True)
    assert (c1, c2, c3) == (1, 2, 3)
    assert a4 is False
    assert c4 == 3  # was NOT incremented on the rejected call
    assert retry > 0


def test_bucket_rolls_over_at_window_boundary():
    rate_limit_service.reset()
    lim = RateLimit(requests=2, window_sec=60)

    # Fill the bucket at t=100.
    check_and_consume("k", lim, now=100)
    check_and_consume("k", lim, now=100)
    rejected, _, _ = check_and_consume("k", lim, now=100)
    assert rejected is False

    # Move to t=160 (next bucket).
    allowed, count, _ = check_and_consume("k", lim, now=160)
    assert allowed
    assert count == 1


def test_different_keys_have_independent_buckets():
    rate_limit_service.reset()
    lim = RateLimit(requests=1)

    a1, _, _ = check_and_consume("user:a", lim, now=100)
    a2, _, _ = check_and_consume("user:b", lim, now=100)
    assert a1 is True
    assert a2 is True

    # Each is now full.
    a3, _, _ = check_and_consume("user:a", lim, now=100)
    a4, _, _ = check_and_consume("user:b", lim, now=100)
    assert a3 is False
    assert a4 is False


def test_retry_after_decreases_within_window():
    """Within the same bucket epoch, retry_after shrinks as time
    advances toward the next bucket boundary."""
    rate_limit_service.reset()
    lim = RateLimit(requests=1, window_sec=60)
    # All three timestamps fall inside bucket epoch 1 (60-119).
    check_and_consume("k", lim, now=70)
    _, _, retry_at_70 = check_and_consume("k", lim, now=70)
    _, _, retry_at_110 = check_and_consume("k", lim, now=110)
    assert retry_at_110 < retry_at_70
    assert retry_at_110 >= 1


# ---------------------------------------------------------------------------
# Middleware integration — sensitive endpoints
# ---------------------------------------------------------------------------


def test_login_endpoint_rate_limited(unauthenticated_client, db, monkeypatch):
    """Hammering /auth/login from one IP triggers 429 quickly."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_MIN", 3)
    rate_limit_service.reset()

    # First 3 requests pass through (returning 401 because no user).
    for _ in range(3):
        r = unauthenticated_client.post(
            "/api/v1/auth/login",
            json={"email": "anyone@x.com", "password": "wrong"},
        )
        assert r.status_code == 401

    # 4th request hits the rate limit.
    r = unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": "anyone@x.com", "password": "wrong"},
    )
    assert r.status_code == 429
    assert "retry-after" in {h.lower() for h in r.headers.keys()}
    assert r.headers["X-RateLimit-Limit"] == "3"
    assert r.headers["X-RateLimit-Remaining"] == "0"
    body = r.json()
    assert "retry_after_sec" in body


def test_password_reset_endpoint_rate_limited(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_RESET_PER_MIN", 2)
    rate_limit_service.reset()

    for _ in range(2):
        r = unauthenticated_client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "x@y.com"},
        )
        assert r.status_code == 200

    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "x@y.com"},
    )
    assert r.status_code == 429


def test_register_endpoint_rate_limited(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_REGISTER_PER_MIN", 2)
    rate_limit_service.reset()

    # Two registrations — the first succeeds 201; the second hits the
    # already-registered email path so 409 is fine. The third hits 429.
    r1 = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "a@x.com", "password": "goodpw1234"},
    )
    assert r1.status_code in (201, 409)
    r2 = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "b@x.com", "password": "goodpw1234"},
    )
    assert r2.status_code in (201, 409)

    r3 = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "c@x.com", "password": "goodpw1234"},
    )
    assert r3.status_code == 429


# ---------------------------------------------------------------------------
# Middleware integration — per-user bucket
# ---------------------------------------------------------------------------


def test_authenticated_get_rate_limited_per_user(client, monkeypatch):
    """A logged-in user hitting any /api/v1/* endpoint past the per-user
    limit gets 429."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MIN_STUDIO", 5)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MIN_PRO", 5)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MIN_FREE", 5)
    rate_limit_service.reset()

    # Use /jobs (existing endpoint that doesn't side-effect external state).
    for _ in range(5):
        r = client.get("/api/v1/jobs")
        assert r.status_code == 200

    r = client.get("/api/v1/jobs")
    assert r.status_code == 429


def test_response_includes_rate_limit_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MIN_STUDIO", 100)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MIN_PRO", 100)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MIN_FREE", 100)
    rate_limit_service.reset()

    r = client.get("/api/v1/jobs")
    assert r.status_code == 200
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers


def test_disabled_rate_limit_passes_through(client, monkeypatch):
    """When RATE_LIMIT_ENABLED=False the middleware doesn't add headers
    and never produces 429s."""
    # The fixture leaves it disabled by default.
    rate_limit_service.reset()
    for _ in range(50):
        r = client.get("/api/v1/jobs")
        assert r.status_code == 200
    # No rate-limit headers when disabled.
    assert "X-RateLimit-Limit" not in r.headers
