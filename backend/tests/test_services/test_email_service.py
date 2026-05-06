"""Tests for T-5.4.8 — SMTP integration for password-reset emails."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.services.email_service import (
    EmailDeliveryError,
    render_password_reset_email,
    send_email,
    send_email_strict,
)


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


def test_render_password_reset_email_includes_secret_and_ttl():
    subject, body = render_password_reset_email(
        recipient_email="user@example.com",
        secret="REAL-SECRET-TOKEN",
        ttl_minutes=30,
    )
    assert "Pratidhvani" in subject
    assert "REAL-SECRET-TOKEN" in body
    assert "30 minutes" in body
    assert "user@example.com" in body


# ---------------------------------------------------------------------------
# Log fallback (no SMTP configured)
# ---------------------------------------------------------------------------


def test_send_email_log_fallback_when_no_smtp(monkeypatch, caplog):
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    with caplog.at_level("INFO"):
        ok = send_email("user@example.com", "Subj", "Body content")
    assert ok is True
    # Body landed in the log so the operator can pick it up.
    assert any("Body content" in r.message for r in caplog.records)
    assert any("EMAIL (SMTP unconfigured" in r.message for r in caplog.records)


def test_send_email_strict_log_fallback_when_no_smtp(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    # Strict variant in unconfigured mode is a no-op (logs and returns).
    send_email_strict("user@example.com", "Subj", "Body")


def test_send_email_rejects_empty_recipient(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    assert send_email("", "Subj", "Body") is False
    assert send_email("   ", "Subj", "Body") is False


def test_send_email_strict_rejects_empty_recipient():
    with pytest.raises(EmailDeliveryError):
        send_email_strict("", "Subj", "Body")


# ---------------------------------------------------------------------------
# SMTP path (mocked)
# ---------------------------------------------------------------------------


def test_send_email_uses_smtp_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "pw")
    monkeypatch.setattr(settings, "SMTP_USE_SSL", False)
    monkeypatch.setattr(settings, "SMTP_USE_STARTTLS", True)
    monkeypatch.setattr(settings, "SMTP_FROM_ADDRESS", "no-reply@example.com")

    fake_smtp = MagicMock()
    fake_smtp.__enter__.return_value = fake_smtp
    fake_smtp.__exit__.return_value = False

    with patch("app.services.email_service.smtplib.SMTP", return_value=fake_smtp):
        ok = send_email("dest@example.com", "Sub", "Hi.")

    assert ok is True
    fake_smtp.starttls.assert_called_once()
    fake_smtp.login.assert_called_once_with("user", "pw")
    fake_smtp.send_message.assert_called_once()


def test_send_email_uses_smtp_ssl_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 465)
    monkeypatch.setattr(settings, "SMTP_USERNAME", None)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
    monkeypatch.setattr(settings, "SMTP_USE_SSL", True)
    monkeypatch.setattr(settings, "SMTP_USE_STARTTLS", False)

    fake_smtp = MagicMock()
    fake_smtp.__enter__.return_value = fake_smtp
    fake_smtp.__exit__.return_value = False

    with patch("app.services.email_service.smtplib.SMTP_SSL", return_value=fake_smtp):
        ok = send_email("dest@example.com", "Sub", "Body")

    assert ok is True
    fake_smtp.starttls.assert_not_called()  # SSL handles encryption
    fake_smtp.login.assert_not_called()  # no creds


def test_send_email_smtp_failure_falls_back_to_log(monkeypatch, caplog):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_USE_STARTTLS", False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", None)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", None)

    fake_smtp = MagicMock()
    fake_smtp.__enter__.return_value = fake_smtp
    fake_smtp.__exit__.return_value = False
    fake_smtp.send_message.side_effect = RuntimeError("network blip")

    with patch("app.services.email_service.smtplib.SMTP", return_value=fake_smtp):
        with caplog.at_level("INFO"):
            ok = send_email("dest@example.com", "Sub", "Body123")

    assert ok is False
    # Body still landed in the log via the fallback so we don't lose data.
    assert any("Body123" in r.message for r in caplog.records)
    assert any("SMTP delivery failed" in r.message for r in caplog.records)


def test_send_email_strict_raises_on_smtp_failure(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_USE_STARTTLS", False)

    fake_smtp = MagicMock()
    fake_smtp.__enter__.return_value = fake_smtp
    fake_smtp.__exit__.return_value = False
    fake_smtp.send_message.side_effect = RuntimeError("nope")

    with patch("app.services.email_service.smtplib.SMTP", return_value=fake_smtp):
        with pytest.raises(EmailDeliveryError):
            send_email_strict("dest@example.com", "Sub", "B")


# ---------------------------------------------------------------------------
# Endpoint integration — password-reset response shape changes with SMTP
# ---------------------------------------------------------------------------


def test_password_reset_response_omits_secret_when_smtp_configured(
    unauthenticated_client, db, monkeypatch
):
    """SaaS posture: SMTP configured → secret is NEVER in the response."""
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_USE_STARTTLS", False)

    from app.services import auth_service
    auth_service.create_user(db, email="reset-smtp@x.com", password="oldpw1234")

    fake_smtp = MagicMock()
    fake_smtp.__enter__.return_value = fake_smtp
    fake_smtp.__exit__.return_value = False

    with patch("app.services.email_service.smtplib.SMTP", return_value=fake_smtp):
        r = unauthenticated_client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "reset-smtp@x.com"},
        )

    assert r.status_code == 200
    body = r.json()
    # SMTP configured → response carries no secret.
    assert body["debug_secret"] is None
    fake_smtp.send_message.assert_called_once()


def test_password_reset_response_returns_secret_when_smtp_unconfigured(
    unauthenticated_client, db, monkeypatch
):
    """Self-host posture: no SMTP → secret IS in the response so operators
    can hand it off out-of-band."""
    monkeypatch.setattr(settings, "SMTP_HOST", None)

    from app.services import auth_service
    auth_service.create_user(db, email="reset-nosmtp@x.com", password="oldpw1234")

    r = unauthenticated_client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset-nosmtp@x.com"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["debug_secret"] is not None
    assert len(body["debug_secret"]) > 16
