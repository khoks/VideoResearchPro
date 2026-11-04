"""Echo's email inbox over IMAP, for self-hosters (T-3.7.4.1).

A dedicated mailbox, polled from the single scheduler tick: the tick keeps one
``scheduled_runs`` row of kind ``echo_imap`` in step with the settings
(``sync_schedule``) and dispatches ``echo.poll_imap`` like any other kind, so
there is no second beat entry. Each message from an allowed sender becomes one
share with ``surface=email_in``, through the same intake, caps and processing
as every other surface.

**Mail is untrusted data.** Anyone can email a mailbox and a From header can be
forged (docs/echo-share-surfaces.md), and that shapes everything here:

- ``ECHO_IMAP_ALLOWED_SENDERS`` decides what is accepted; empty accepts nothing.
  A message that does not name exactly one allowed sender is dropped on its
  headers, before its body is ever fetched.
- A message is a **text** share, always. The poller never makes a URL share,
  which would have the server fetch an address a stranger chose, past the
  article extractor's lack of a private-address guard. Attachments are listed
  on the share and not read, so a forged message cannot drive vision or Whisper
  spend. A link in a mail stays text in the inbox.
- A message is never the user's own words. ``author_is_tenant`` stays False,
  and ``echo_intake_service`` refuses to make it True for this surface, so mail
  cannot reach voice signals (D-089 item 1).
- Nothing from a message goes in ``user_annotation``: that field is the user's.
- The log carries counts and exception types, never a body, a subject, an
  address or the password.

**Exactly one share per message.** The share and an ``echo_email_messages`` row
are committed together, keyed on the ``Message-ID`` (or on the raw bytes when a
message has none), so a re-poll adds nothing, and a share the user deleted does
not come back. A message is read with ``BODY.PEEK`` and flagged ``\\Seen`` only
once it has been dealt with, which is what the next poll's ``UNSEEN`` search
skips. Nothing here deletes mail: a dropped message stays in the mailbox, read,
and marking it unread puts it in front of the next poll.
"""
from __future__ import annotations

import hashlib
import imaplib
import json
import logging
import re
import ssl
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesHeaderParser, BytesParser
from typing import Any, Callable

from bs4 import BeautifulSoup
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.echo_email_message import EchoEmailMessage
from app.models.user import User
from app.services import auth_service, echo_intake_service, echo_processing_service, scheduler_service
from app.services.echo_intake_service import EMAIL_SURFACE, InvalidShare
from app.services.tier_service import has_feature

logger = logging.getLogger(__name__)

KIND = "echo_imap"
#: One mailbox per install, so one row. The tick hands this to the task.
TARGET = "mailbox"
CONTENT_TYPE = "email"

#: Most messages one poll takes, oldest first; the next tick takes the rest.
#: A solo worker does nothing else while it polls.
MAX_PER_POLL = 50
_SOCKET_TIMEOUT_SEC = 30
_SUBJECT_MAX = 300
_ATTACHMENTS_LISTED = 20
_SIZE_RE = re.compile(rb"RFC822\.SIZE (\d+)")


@dataclass
class PollReport:
    """What one poll did. ``status`` says why when it did nothing."""

    status: str
    accepted: int = 0
    duplicates: int = 0
    dropped_sender: int = 0
    empty: int = 0
    too_large: int = 0
    unreadable: int = 0
    failed: int = 0
    #: Unread messages past ``MAX_PER_POLL``, left for the next tick.
    waiting: int = 0

    def counts(self) -> dict[str, int]:
        return {k: v for k, v in self.__dict__.items() if k != "status" and v}


@dataclass(frozen=True)
class ParsedMail:
    subject: str
    text: str
    date: str | None = None
    attachments: list[dict[str, str]] = field(default_factory=list)


def allowed_senders() -> frozenset[str]:
    """``ECHO_IMAP_ALLOWED_SENDERS`` as lower-cased addresses. Exact addresses
    only: a domain or a wildcard would widen what a forged From can reach."""
    raw = settings.ECHO_IMAP_ALLOWED_SENDERS or ""
    return frozenset(a.strip().lower() for a in raw.split(",") if a.strip())


def sender_of(msg: EmailMessage) -> str | None:
    """The sender, lower-cased, when the message names exactly one: one
    well-formed From header holding one address and no group. Anything else
    is refused, not guessed at. A second address or header claims an allowed
    sender beside the real one, and a malformed header is worse: Python reads
    ``owner@x.com <evil@y.com>`` as the first address, where a mail provider's
    DMARC check reads the second."""
    headers = msg.get_all("From") or []
    if len(headers) != 1:
        return None
    header = headers[0]
    if header.defects or len(header.addresses) != 1 or header.groups[0].display_name is not None:
        return None
    address = (header.addresses[0].addr_spec or "").strip().lower()
    return address if "@" in address else None


def message_key(message_id: str | None, raw: bytes | None = None) -> str | None:
    """The dedup key: the ``Message-ID`` if there is one, else the bytes."""
    source = (message_id or "").strip().encode("utf-8", "surrogateescape")
    if not source:
        source = raw or b""
    return hashlib.sha256(source).hexdigest() if source else None


def _html_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "title"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def _part_text(part: EmailMessage) -> str:
    try:
        content = part.get_content()
    except (LookupError, UnicodeError):  # an unknown or wrong charset
        content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if not isinstance(content, str):
        return ""
    if part.get_content_type() == "text/html":
        content = _html_text(content)
    return content.replace("\x00", "").strip()


def _body_text(msg: EmailMessage) -> str:
    """The plain-text body, or the HTML one read as text when plain is blank
    (some senders fill a multipart/alternative's plain part with nothing)."""
    for kind in ("plain", "html"):
        part = msg.get_body(preferencelist=(kind,))
        if part is not None:
            text = _part_text(part)
            if text:
                return text
    return ""


def parse_mail(raw: bytes) -> ParsedMail:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    attachments = []
    for part in msg.iter_attachments():
        if len(attachments) == _ATTACHMENTS_LISTED:
            break
        name = " ".join(str(part.get_filename() or "").split())[:200]
        attachments.append({"name": name or "unnamed", "type": part.get_content_type()})
    date = msg.get("Date")
    return ParsedMail(
        subject=" ".join(str(msg.get("Subject") or "").split())[:_SUBJECT_MAX],
        text=_body_text(msg),
        date=str(date)[:64] if date else None,
        attachments=attachments,
    )


def _capped(text: str) -> str:
    """Keep what fits. A mail has nobody to refuse to, so a text over the cap
    is cut and says so; the whole message stays in the mailbox."""
    limit = settings.ECHO_SHARE_TEXT_MAX_CHARS
    if len(text) <= limit:
        return text
    note = f"\n\n[Cut at {limit:,} characters. The whole message is in the mailbox.]"
    return text[: max(0, limit - len(note))] + note


# ---------------------------------------------------------------------------
# IMAP
# ---------------------------------------------------------------------------


def _connect() -> imaplib.IMAP4:
    """Signed in over TLS, with the certificate and host name verified."""
    client = imaplib.IMAP4_SSL(
        settings.ECHO_IMAP_HOST,
        settings.ECHO_IMAP_PORT,
        ssl_context=ssl.create_default_context(),
        timeout=_SOCKET_TIMEOUT_SEC,
    )
    try:
        client.login(settings.ECHO_IMAP_USERNAME, settings.ECHO_IMAP_PASSWORD)
    except Exception:
        _hang_up(client)
        raise
    return client


def _hang_up(client: Any) -> None:
    try:
        client.logout()
    except Exception:  # noqa: BLE001 — the socket is going away either way
        logger.debug("echo imap: logout failed")


def _mailbox_name(name: str) -> str:
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unseen_uids(client: Any) -> list[str]:
    status, data = client.uid("SEARCH", None, "UNSEEN")
    if status != "OK":
        raise imaplib.IMAP4.error("SEARCH was refused")
    return [uid.decode("ascii") for uid in (data[0] or b"").split()] if data else []


def _fetch(client: Any, uid: str, items: str) -> tuple[bytes, bytes | None]:
    """A FETCH's data items and its literal. imaplib mixes ``(items, literal)``
    tuples with bare trailing items, and a server may put an item on either
    side of the literal, so the items are joined before anyone reads them."""
    status, data = client.uid("FETCH", uid, items)
    if status != "OK":
        raise imaplib.IMAP4.error("FETCH was refused")
    parts: list[bytes] = []
    literal = None
    for item in data or []:
        if isinstance(item, tuple):
            parts.append(item[0])
            literal = item[1] if literal is None else literal
        elif isinstance(item, bytes):
            parts.append(item)
    return b" ".join(parts), literal


def _mark_seen(client: Any, uid: str) -> None:
    client.uid("STORE", uid, "+FLAGS.SILENT", r"(\Seen)")


# ---------------------------------------------------------------------------
# One message
# ---------------------------------------------------------------------------


def _already_taken(db: Session, tenant_id: str, key: str) -> bool:
    return (
        db.query(EchoEmailMessage.id)
        .filter(EchoEmailMessage.tenant_id == tenant_id, EchoEmailMessage.message_key == key)
        .first()
        is not None
    )


def _source(sender: str, message_id: str | None, mail: ParsedMail) -> dict:
    out: dict[str, Any] = {"from": sender}
    if mail.subject:
        out["title"] = mail.subject
    if message_id:
        out["message_id"] = message_id[:300]
    if mail.date:
        out["date"] = mail.date
    if mail.attachments:
        out["attachments"] = mail.attachments
    return out


def _store(db: Session, user: User, key: str, sender: str, message_id: str | None, mail: ParsedMail) -> bool:
    """The share and its ledger row, in one commit. False if a poll running
    at the same moment took the message first."""
    share = echo_intake_service.new_text_share(
        user.id,
        user.id,
        text=_capped(mail.text or mail.subject),
        content_type=CONTENT_TYPE,
        surface=EMAIL_SURFACE,
        source=_source(sender, message_id, mail),
    )
    db.add(share)
    db.add(EchoEmailMessage(tenant_id=user.id, message_key=key))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    echo_processing_service.enqueue(share, user)
    return True


def _take(db: Session, client: Any, uid: str, user: User, allowed: frozenset[str], report: PollReport) -> None:
    items, head = _fetch(client, uid, "(RFC822.SIZE BODY.PEEK[HEADER])")
    if head is None:
        report.unreadable += 1  # expunged since the search: nothing to flag
        return
    try:
        headers = BytesHeaderParser(policy=policy.default).parsebytes(head)
        sender = sender_of(headers)
        raw_id = headers.get("Message-ID")
    except Exception:  # noqa: BLE001 — a header the parser cannot read is untrusted input
        report.unreadable += 1
        _mark_seen(client, uid)
        return
    if sender is None or sender not in allowed:
        report.dropped_sender += 1
        _mark_seen(client, uid)
        return

    cap = settings.ECHO_SHARE_MAX_BYTES
    size = _SIZE_RE.search(items)
    if size and int(size.group(1)) > cap:
        report.too_large += 1
        _mark_seen(client, uid)
        return
    message_id = str(raw_id).strip() if raw_id else None
    key = message_key(message_id)
    if key and _already_taken(db, user.id, key):
        report.duplicates += 1
        _mark_seen(client, uid)
        return

    _items, raw = _fetch(client, uid, "(BODY.PEEK[])")
    if not raw:
        report.unreadable += 1
        return
    if len(raw) > cap:
        report.too_large += 1
        _mark_seen(client, uid)
        return
    key = key or message_key(None, raw)
    if key is None or _already_taken(db, user.id, key):
        report.duplicates += 1
        _mark_seen(client, uid)
        return
    try:
        mail = parse_mail(raw)
    except Exception:  # noqa: BLE001 — a body the parser cannot read is untrusted input
        report.unreadable += 1
        _mark_seen(client, uid)
        return
    if not (mail.text or mail.subject):
        report.empty += 1
        _mark_seen(client, uid)
        return
    try:
        stored = _store(db, user, key, sender, message_id, mail)
    except InvalidShare:
        report.unreadable += 1
        _mark_seen(client, uid)
        return
    if stored:
        report.accepted += 1
    else:
        report.duplicates += 1
    _mark_seen(client, uid)


# ---------------------------------------------------------------------------
# The poll
# ---------------------------------------------------------------------------


def _tenant(db: Session) -> User | None:
    email = (settings.ECHO_IMAP_TENANT_EMAIL or "").strip()
    return auth_service.get_user_by_email(db, email) if email else None


def _refusal(db: Session) -> tuple[str | None, User | None]:
    """Why a poll must not open the mailbox, or the tenant it polls for. The
    Studio check runs on every poll, as on every share-token use, so a
    downgraded account's mail stops without anyone touching the settings."""
    if not settings.ECHO_IMAP_ENABLED:
        return "disabled", None
    if not (settings.ECHO_IMAP_HOST and settings.ECHO_IMAP_USERNAME and settings.ECHO_IMAP_PASSWORD):
        logger.warning("echo imap: ECHO_IMAP_HOST, _USERNAME and _PASSWORD are needed; not polling")
        return "unconfigured", None
    user = _tenant(db)
    if user is None:
        logger.warning("echo imap: ECHO_IMAP_TENANT_EMAIL names no account; not polling")
        return "no_tenant", None
    if not has_feature(user, "echo_personal_brain"):
        logger.warning("echo imap: the tenant's plan has no Echo; not polling")
        return "not_entitled", None
    if not allowed_senders():
        # Not "drop everything": the mailbox is left alone, so mail waiting
        # there is still unread when the owner fills the list in.
        logger.warning("echo imap: ECHO_IMAP_ALLOWED_SENDERS is empty, which accepts nothing; not polling")
        return "no_allowed_senders", None
    return None, user


def poll(db: Session, *, connect: Callable[[], Any] | None = None) -> PollReport:
    """One pass over the mailbox's unread mail. Never raises: a mailbox that
    cannot be reached is logged by exception type alone (its message can quote
    the server) and tried again at the next tick; what was stored stays."""
    refused, user = _refusal(db)
    if refused or user is None:
        return PollReport(refused or "no_tenant")
    allowed = allowed_senders()

    report = PollReport("ok")
    client = None
    try:
        client = (connect or _connect)()
        status, _ = client.select(_mailbox_name(settings.ECHO_IMAP_FOLDER))
        if status != "OK":
            raise imaplib.IMAP4.error("SELECT was refused")
        uids = _unseen_uids(client)
        report.waiting = max(0, len(uids) - MAX_PER_POLL)
        for uid in uids[:MAX_PER_POLL]:
            try:
                _take(db, client, uid, user, allowed, report)
            except (imaplib.IMAP4.error, OSError):
                raise  # the connection is gone: stop here, the rest wait
            except Exception as e:  # noqa: BLE001 — one message must not cost the others
                db.rollback()
                report.failed += 1
                logger.warning("echo imap: a message could not be stored (%s)", type(e).__name__)
    except Exception as e:  # noqa: BLE001 — the tick's next run is the retry
        db.rollback()
        report.status = "error"
        logger.warning("echo imap: poll failed (%s)", type(e).__name__)
    finally:
        if client is not None:
            _hang_up(client)
    if report.status == "error" or report.counts():
        logger.info("echo imap: %s %s", report.status, report.counts())
    return report


def sync_schedule(db: Session) -> None:
    """Keep the one ``scheduled_runs`` row in step with the settings: there
    while the inbox is on, gone when it is off, on the tenant's tier queue.
    Called from the tick, so an install needs no step of its own, and a row
    already in place is left alone: its ``next_run_at`` is the schedule."""
    run = scheduler_service.get_run(db, KIND, TARGET)
    if not settings.ECHO_IMAP_ENABLED:
        if run is not None:
            scheduler_service.unschedule(db, KIND, TARGET)
        return
    user = _tenant(db)
    tenant_id = user.id if user else None
    cadence = scheduler_service.normalise_cadence(
        {
            "cadence": "every",
            "seconds": max(scheduler_service.MIN_EVERY_SECONDS, settings.SCHEDULER_TICK_SECONDS),
        }
    )
    if run is not None and run.tenant_id == tenant_id and json.loads(run.cadence_json) == cadence:
        return
    scheduler_service.schedule(
        db,
        kind=KIND,
        target_id=TARGET,
        cadence=cadence,
        tenant_id=tenant_id,
        start_at=scheduler_service.utcnow(),
    )
