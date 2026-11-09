"""Email delivery — T-5.4.8.

Pluggable email backend. Two modes:

- **SMTP** — when ``SMTP_HOST`` is configured, deliver via ``smtplib``
  with optional STARTTLS / authentication. The standard production path
  (and the SaaS path).
- **Logged** — when ``SMTP_HOST`` is unset, log the rendered email
  body to stderr instead. The self-host fallback so password-reset
  flows work without operators needing to set up SMTP. Until 2026-11-03
  the password-reset endpoint also returned the secret in the response
  (``debug_secret``), which let any caller reset any account; the log is
  now the only fallback.

The service is **fail-safe**: any SMTP error is logged but does NOT
propagate to the caller. The user-facing endpoint (e.g. the
password-reset request) returns the same generic 200 either way.

Future work (out of scope here):
- Provider integrations (Resend, Postmark, SendGrid) for SaaS.
- HTML templates with branding (vs the plain-text-only flow today).
- Bounce / complaint webhook handling.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings
from app.utils.shared_url_log import traceback_without_text

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised by ``send_email_strict`` (test-only) on delivery failure.

    Production callers use ``send_email`` which never raises."""


def _is_smtp_configured() -> bool:
    """SMTP delivery requires at minimum a host. Username / password /
    from-address are optional (some local relays accept anonymous mail)."""
    return bool(getattr(settings, "SMTP_HOST", None))


def _from_address() -> str:
    """Sender envelope. Defaults to ``no-reply@<host>`` when unset."""
    explicit = getattr(settings, "SMTP_FROM_ADDRESS", None)
    if explicit:
        return explicit
    host = getattr(settings, "SMTP_HOST", "localhost") or "localhost"
    return f"no-reply@{host}"


def _build_smtp(host: str, port: int):
    """Open an SMTP connection. Wraps SSL vs STARTTLS depending on
    ``SMTP_USE_SSL`` / ``SMTP_USE_STARTTLS``. Caller is responsible for
    quitting the connection."""
    use_ssl = getattr(settings, "SMTP_USE_SSL", False)
    if use_ssl:
        return smtplib.SMTP_SSL(host, port, timeout=10)
    smtp = smtplib.SMTP(host, port, timeout=10)
    if getattr(settings, "SMTP_USE_STARTTLS", True):
        smtp.starttls()
    return smtp


def build_message(
    to: str, subject: str, body: str, *, html: str | None = None, message_id: str | None = None
) -> EmailMessage:
    """The message as sent: plain text, plus an HTML alternative when given
    (S-6.4.2), and a caller-chosen ``Message-ID`` so a retried send is the
    same message to the receiving server."""
    msg = EmailMessage()
    msg["From"] = _from_address()
    msg["To"] = to
    msg["Subject"] = subject
    if message_id:
        msg["Message-ID"] = message_id
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _send_via_smtp(
    to: str, subject: str, body: str, *, html: str | None = None, message_id: str | None = None
) -> None:
    host = settings.SMTP_HOST
    port = int(getattr(settings, "SMTP_PORT", 587) or 587)
    msg = build_message(to, subject, body, html=html, message_id=message_id)

    with _build_smtp(host, port) as smtp:
        username = getattr(settings, "SMTP_USERNAME", None)
        password = getattr(settings, "SMTP_PASSWORD", None)
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)


def _log_email(to: str, subject: str, body: str, *, html: str | None = None) -> None:
    """Self-host fallback: write the email to the log so the operator
    can hand-deliver it. Not for production SaaS use — operators should
    set up SMTP. An HTML part is noted, not logged."""
    logger.info(
        "EMAIL (SMTP unconfigured — log fallback) → to=%s subject=%r%s\n"
        "----- BEGIN EMAIL BODY -----\n%s\n----- END EMAIL BODY -----",
        to,
        subject,
        f" (HTML part of {len(html)} characters not logged)" if html else "",
        body,
    )


def send_email(
    to: str, subject: str, body: str, *, html: str | None = None, message_id: str | None = None
) -> bool:
    """Send an email. Returns True on success, False on failure.

    Never raises. Uses SMTP when ``SMTP_HOST`` is configured; otherwise
    falls back to logging the email body so self-host operators can
    deliver out-of-band. ``html`` adds an HTML alternative to the plain
    text, and ``message_id`` pins the Message-ID header (S-6.4.2).
    """
    if not to or not to.strip():
        logger.warning("send_email: empty recipient — dropping")
        return False

    if not _is_smtp_configured():
        _log_email(to, subject, body, html=html)
        return True

    try:
        _send_via_smtp(to, subject, body, html=html, message_id=message_id)
        # Neither the address nor the subject, which can hold a user's own
        # question (a saved search's alert). The log fallback below is the
        # one place an address belongs: the operator has to deliver it.
        logger.info("send_email: delivered by SMTP")
        return True
    except Exception as e:
        # As the success line: no address and no subject, and the type and
        # frames rather than the error's text, since smtplib's refusals quote
        # the recipient (T-4.11.4.2). The fallback below writes the email whole
        # for the operator to deliver, the one place an address belongs.
        logger.error(
            "send_email: SMTP delivery failed — falling back to log so the "
            "message is at least preserved: %s",
            traceback_without_text(e),
        )
        _log_email(to, subject, body, html=html)
        return False


def send_email_strict(to: str, subject: str, body: str) -> None:
    """Strict variant — raises ``EmailDeliveryError`` on failure. Used
    by tests; production code should always use the fail-safe ``send_email``."""
    if not to or not to.strip():
        raise EmailDeliveryError("empty recipient")
    if not _is_smtp_configured():
        _log_email(to, subject, body)
        return
    try:
        _send_via_smtp(to, subject, body)
    except Exception as e:
        raise EmailDeliveryError(str(e)) from e


# ---------------------------------------------------------------------------
# Templates — kept inline for now; promote to docs/templates/ if more
# emails ship beyond password-reset.
# ---------------------------------------------------------------------------


def password_reset_page_url() -> str:
    """The address of the page that takes a reset code (``/reset-password``).

    The bare page, never with the code in it: a secret in a URL ends up in
    browser history, proxy logs and Referer headers."""
    return f"{settings.APP_BASE_URL.rstrip('/')}/reset-password"


def render_password_reset_email(
    *, recipient_email: str, secret: str, ttl_minutes: int
) -> tuple[str, str]:
    """Return ``(subject, body)`` for the password-reset email.

    The email is the only way the code reaches the user (the request
    endpoint never returns it), so it names the page to paste it into: the
    reader may open it on another device, or after closing the tab that
    asked for it, where nothing else leads to that page."""
    subject = "Pratidhvani — Password reset request"
    body = (
        f"Hello,\n\n"
        f"A password reset was requested for your Pratidhvani account "
        f"({recipient_email}). If this was you, open "
        f"{password_reset_page_url()} and paste the code below into the "
        f"form within {ttl_minutes} minutes:\n\n"
        f"    {secret}\n\n"
        f"If you didn't request this, you can safely ignore this email "
        f"— your password remains unchanged.\n\n"
        f"— Pratidhvani"
    )
    return subject, body
