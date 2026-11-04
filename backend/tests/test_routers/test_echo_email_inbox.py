"""Echo's email inbox (T-3.7.4.1): a mailbox polled over IMAP from the tick.

No real mailbox exists here, so nothing proves the poller against a live
server. A fake client covers the behaviour, shaped like imaplib's answers, and
one test runs the real ``imaplib`` over a loopback socket against a scripted
server, so the fake's shape is not just an assumption.

Each message arrives as bytes built by ``email.message``, and the assertions
sit at the production callers: the scheduler tick, the Celery task, the inbox
route, signal extraction.
"""
from __future__ import annotations

import imaplib
import json
import re
import socketserver
import ssl
import threading
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.models.echo_email_message import EchoEmailMessage
from app.models.scheduled_run import ScheduledRun
from app.models.share import Share
from app.services import (
    auth_service,
    echo_imap_service,
    echo_intake_service,
    echo_processing_service,
    echo_signal_extraction,
    echo_vectors,
    scheduler_service,
)
from app.tasks import echo_tasks, scheduler_tasks
from app.tasks.celery_app import _beat_schedule

SHARES = "/api/v1/echo/shares"
OWNER = "imap-owner@example.com"
ALLOWED = "me@example.com"
PASSWORD = "imap-password-never-logged"
BODY = "A long note about Mughal tariffs, forwarded by hand."


def _studio(db, email):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


def _mail(
    *,
    sender: str = f"Me Myself <{ALLOWED}>",
    subject: str | None = "Tariffs",
    body: str = BODY,
    message_id: str | None = "<one@mail.example>",
    html: str | None = None,
    attach: tuple[str, str, bytes] | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "inbox@example.com"
    if subject is not None:
        msg["Subject"] = subject
    if message_id:
        msg["Message-ID"] = message_id
    msg["Date"] = "Wed, 04 Nov 2026 09:00:00 +0000"
    msg.set_content(body)
    if html is not None:
        msg.add_alternative(html, subtype="html")
    if attach is not None:
        name, mime, data = attach
        maintype, subtype = mime.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


def _raw_mail(*header_lines: bytes, body: bytes = BODY.encode()) -> bytes:
    """For the headers ``EmailMessage`` refuses to write: forgeries are not
    well-formed mail."""
    return b"\r\n".join(header_lines) + b"\r\n\r\n" + body


class FakeImap:
    """The calls the poller makes, answering in imaplib's shapes."""

    def __init__(self, messages: dict[int, bytes] | list[bytes] | None = None):
        if isinstance(messages, list):
            messages = {i + 1: raw for i, raw in enumerate(messages)}
        self.messages = dict(messages or {})
        self.unseen = set(self.messages)
        self.fetched: list[tuple[str, str]] = []
        self.flagged: list[str] = []
        self.selected: str | None = None
        self.logged_out = False
        self.fail_store = False

    def select(self, mailbox, readonly=False):
        self.selected = mailbox
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            assert args == (None, "UNSEEN")
            return "OK", [" ".join(str(u) for u in sorted(self.unseen)).encode()]
        if command == "FETCH":
            uid, items = args
            self.fetched.append((uid, items))
            raw = self.messages[int(uid)]
            if "HEADER" in items:
                head = raw.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0] + b"\r\n\r\n"
                return "OK", [(f"1 (UID {uid} RFC822.SIZE {len(raw)} BODY[HEADER] {{{len(head)}}}".encode(), head), b")"]
            return "OK", [(f"1 (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        if command == "STORE":
            uid, op, flags = args
            assert op == "+FLAGS.SILENT" and flags == r"(\Seen)"
            if self.fail_store:
                raise imaplib.IMAP4.abort("socket went away")
            self.flagged.append(uid)
            self.unseen.discard(int(uid))
            return "OK", [None]
        raise AssertionError(command)

    def logout(self):
        self.logged_out = True
        return "BYE", [b"bye"]

    def bodies_fetched(self) -> list[str]:
        return [uid for uid, items in self.fetched if "HEADER" not in items]


@pytest.fixture
def chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield client
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


@pytest.fixture
def owner(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    monkeypatch.setattr(settings, "ECHO_IMAP_ENABLED", True)
    monkeypatch.setattr(settings, "ECHO_IMAP_HOST", "imap.example.com")
    monkeypatch.setattr(settings, "ECHO_IMAP_USERNAME", "inbox@example.com")
    monkeypatch.setattr(settings, "ECHO_IMAP_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "ECHO_IMAP_TENANT_EMAIL", OWNER)
    monkeypatch.setattr(settings, "ECHO_IMAP_ALLOWED_SENDERS", f"{ALLOWED}, Phone@Example.com ,")
    user, headers = _studio(db, OWNER)
    return user, headers


def _poll(db, fake):
    return echo_imap_service.poll(db, connect=lambda: fake)


def _shares(db, user):
    return db.query(Share).filter(Share.tenant_id == user.id).all()


# ---------------------------------------------------------------------------
# A message becomes a share
# ---------------------------------------------------------------------------


def test_a_message_from_an_allowed_sender_lands_in_the_inbox_as_context(unauthenticated_client, db, owner):
    user, headers = owner
    fake = FakeImap([_mail()])
    report = _poll(db, fake)
    assert report.status == "ok" and report.accepted == 1

    items = unauthenticated_client.get(SHARES, headers=headers).json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["surface"] == "email_in" and item["kind"] == "text" and item["content_type"] == "email"
    assert item["text"].strip() == BODY
    assert item["author_is_tenant"] is False, "mail is never the user's own words"
    assert item["user_annotation"] is None, "that field is the user's alone"
    assert item["source"]["from"] == ALLOWED and item["source"]["title"] == "Tariffs"
    assert item["source"]["message_id"] == "<one@mail.example>"
    assert fake.selected == '"INBOX"' and fake.logged_out
    assert fake.flagged == ["1"], "dealt with, so the next UNSEEN search skips it"


def test_it_goes_through_the_same_processing_as_every_share(db, owner, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARE_PROCESSING", "celery")
    with patch("app.services.task_routing_service.dispatch_for_user") as dispatch:
        _poll(db, FakeImap([_mail()]))
    share = _shares(db, owner[0])[0]
    task, user, share_id = dispatch.call_args.args
    assert task.name == "echo.process_share" and user.id == owner[0].id and share_id == share.id


def test_the_subject_titles_and_embeds_it_and_a_processed_mail_stays_context(db, owner, chroma):
    user, _ = owner
    _poll(db, FakeImap([_mail(subject="Akbar's revenue system")]))
    share = _shares(db, user)[0]
    assert echo_processing_service.process_share(db, share.id).state == "processed"
    db.refresh(share)
    assert json.loads(share.processing_json)["title"] == "Akbar's revenue system"
    col = chroma.get_collection(settings.CHROMA_SHARES_COLLECTION_NAME)
    got = col.get(ids=[echo_vectors.share_vector_id(share.id)], include=["documents", "metadatas"])
    assert got["documents"][0].startswith("Akbar's revenue system")
    assert got["metadatas"][0]["surface"] == "email_in"
    assert got["metadatas"][0]["author_is_tenant"] is False and got["metadatas"][0]["voice_eligible"] is False


def test_html_only_mail_is_read_as_text_and_runs_no_script(db, owner):
    html = "<html><head><style>p{color:red}</style></head><body><p>Hello <b>there</b></p><script>alert(1)</script></body></html>"
    msg = EmailMessage()
    msg["From"] = ALLOWED
    msg["Subject"] = "Html"
    msg["Message-ID"] = "<html@x>"
    msg.set_content(html, subtype="html")
    _poll(db, FakeImap([msg.as_bytes()]))
    text = _shares(db, owner[0])[0].extracted_text
    assert "Hello" in text and "there" in text
    assert "alert" not in text and "color" not in text and "<p>" not in text


def test_a_blank_plain_part_falls_back_to_the_html_part(db, owner):
    _poll(db, FakeImap([_mail(body="  \n", html="<p>The real words</p>")]))
    assert "The real words" in _shares(db, owner[0])[0].extracted_text


def test_a_subject_with_no_body_is_kept_and_a_message_with_neither_is_not(db, owner):
    fake = FakeImap([_mail(body="", subject="Just the subject"), _mail(body="", subject=None, message_id="<blank@x>")])
    report = _poll(db, fake)
    assert report.accepted == 1 and report.empty == 1
    assert _shares(db, owner[0])[0].extracted_text == "Just the subject"
    assert fake.flagged == ["1", "2"]


def test_an_attachment_is_listed_and_not_read(db, owner):
    """A forged message must not be able to spend vision or Whisper calls."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    _poll(db, FakeImap([_mail(attach=("scan.png", "image/png", png))]))
    share = _shares(db, owner[0])[0]
    assert share.file_path is None and json.loads(share.raw_payload_json)["kind"] == "text"
    assert echo_intake_service.load_payload(share)["source"]["attachments"] == [{"name": "scan.png", "type": "image/png"}]


def test_a_lone_link_stays_text_so_mail_cannot_make_the_server_fetch(db, owner):
    """The extractor behind a URL share has no private-address guard, which
    is fine for a signed-in user and not for a stranger's message."""
    with patch("app.services.echo_intake_service.create_url_share") as url_share:
        _poll(db, FakeImap([_mail(body="http://169.254.169.254/latest/meta-data/\n")]))
    url_share.assert_not_called()
    share = _shares(db, owner[0])[0]
    assert share.content_type == "email" and echo_intake_service.load_payload(share)["kind"] == "text"


# ---------------------------------------------------------------------------
# Who may send
# ---------------------------------------------------------------------------


def test_a_sender_not_on_the_list_is_dropped_on_its_headers(db, owner):
    fake = FakeImap([_mail(sender="Stranger <stranger@evil.example>")])
    report = _poll(db, fake)
    assert report.dropped_sender == 1 and report.accepted == 0 and not _shares(db, owner[0])
    assert fake.bodies_fetched() == [], "a dropped message's body never enters the process"
    assert all("PEEK" in items for _, items in fake.fetched)
    assert fake.flagged == ["1"], "or it would be looked at again every tick and hold up the rest"
    assert db.query(EchoEmailMessage).count() == 0, "so marking it unread lets a later poll take it"


def test_the_list_is_exact_and_ignores_case(db, owner):
    fake = FakeImap(
        [
            _mail(sender="phone@EXAMPLE.com", message_id="<a@x>"),
            _mail(sender="me@example.com.evil.example", message_id="<b@x>"),
            _mail(sender="not-me@example.com", message_id="<c@x>"),
        ]
    )
    report = _poll(db, fake)
    assert report.accepted == 1 and report.dropped_sender == 2


@pytest.mark.parametrize(
    "header",
    [
        b"From: me@example.com, stranger@evil.example",
        b"From: me@example.com <stranger@evil.example>",
        b"From: <me@example.com> stranger@evil.example",
        b"From: me@example.com stranger@evil.example",
        b"From: <stranger@evil.example> <me@example.com>",
        b"From: friends: me@example.com;",
        b'From: "me@example.com" <stranger@evil.example>',
        b"From: me@example.com\r\nFrom: stranger@evil.example",
        b"Sender: me@example.com",
        b"Reply-To: me@example.com",
    ],
)
def test_a_from_that_is_not_one_plain_allowed_address_is_dropped(db, owner, header):
    fake = FakeImap([_raw_mail(header, b"Subject: forged", b"Message-ID: <forged@x>")])
    report = _poll(db, fake)
    assert report.dropped_sender == 1 and report.accepted == 0 and not _shares(db, owner[0])


def test_an_empty_list_accepts_nothing_and_leaves_the_mailbox_alone(db, owner, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_IMAP_ALLOWED_SENDERS", " , ")
    connect = MagicMock()
    report = echo_imap_service.poll(db, connect=connect)
    assert report.status == "no_allowed_senders" and not _shares(db, owner[0])
    connect.assert_not_called()


def test_a_list_of_blanks_is_an_empty_list(monkeypatch):
    monkeypatch.setattr(settings, "ECHO_IMAP_ALLOWED_SENDERS", " , ,")
    assert echo_imap_service.allowed_senders() == frozenset()


# ---------------------------------------------------------------------------
# A re-poll adds nothing
# ---------------------------------------------------------------------------


def test_a_re_poll_adds_nothing(db, owner):
    user, _ = owner
    fake = FakeImap([_mail()])
    _poll(db, fake)
    fake.unseen = {1}  # the flag did not stick, or a client marked it unread
    fake.fetched.clear()
    report = _poll(db, fake)
    assert report.accepted == 0 and report.duplicates == 1
    assert len(_shares(db, user)) == 1
    assert fake.bodies_fetched() == [], "the Message-ID is enough to know"
    assert fake.flagged == ["1", "1"]


def test_the_same_message_id_under_two_uids_is_one_share(db, owner):
    report = _poll(db, FakeImap({7: _mail(), 9: _mail()}))
    assert report.accepted == 1 and report.duplicates == 1
    assert len(_shares(db, owner[0])) == 1


def test_a_lost_flag_does_not_duplicate(db, owner):
    user, _ = owner
    fake = FakeImap([_mail()])
    fake.fail_store = True
    report = _poll(db, fake)
    assert report.status == "error" and len(_shares(db, user)) == 1
    fake.fail_store = False
    report = _poll(db, fake)
    assert report.duplicates == 1 and len(_shares(db, user)) == 1


def test_a_message_with_no_message_id_is_deduplicated_on_its_bytes(db, owner):
    user, _ = owner
    fake = FakeImap({1: _mail(message_id=None), 2: _mail(message_id=None), 3: _mail(message_id=None, body="Other words.")})
    report = _poll(db, fake)
    assert report.accepted == 2 and report.duplicates == 1
    assert len(_shares(db, user)) == 2


def test_a_deleted_share_does_not_come_back(unauthenticated_client, db, owner):
    user, headers = owner
    fake = FakeImap([_mail()])
    _poll(db, fake)
    share_id = _shares(db, user)[0].id
    assert unauthenticated_client.delete(f"{SHARES}/{share_id}", headers=headers).status_code == 200
    fake.unseen = {1}
    report = _poll(db, fake)
    assert report.duplicates == 1 and not _shares(db, user)


def test_two_polls_at_once_store_one_share(db, owner):
    """The ledger's unique key, not the check before it, is what settles it."""
    user, _ = owner
    with patch.object(echo_imap_service, "_already_taken", return_value=False):
        first = _poll(db, FakeImap([_mail()]))
        second = _poll(db, FakeImap([_mail()]))
    assert first.accepted == 1 and second.accepted == 0 and second.duplicates == 1
    assert len(_shares(db, user)) == 1


# ---------------------------------------------------------------------------
# Same caps
# ---------------------------------------------------------------------------


def test_a_message_over_the_file_cap_is_not_downloaded(db, owner, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARE_MAX_BYTES", 100)
    fake = FakeImap([_mail(body="x" * 500)])
    report = _poll(db, fake)
    assert report.too_large == 1 and not _shares(db, owner[0])
    assert fake.bodies_fetched() == [] and fake.flagged == ["1"]


def test_text_over_the_cap_is_cut_and_says_so(db, owner, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARE_TEXT_MAX_CHARS", 200)
    _poll(db, FakeImap([_mail(body="y" * 500)]))
    text = _shares(db, owner[0])[0].extracted_text
    assert len(text) <= 200 and "the mailbox" in text and text.startswith("yyy")


def test_one_poll_takes_a_bounded_number_oldest_first(db, owner, monkeypatch):
    monkeypatch.setattr(echo_imap_service, "MAX_PER_POLL", 2)
    fake = FakeImap([_mail(message_id=f"<n{i}@x>", body=f"Message {i}") for i in range(3)])
    report = _poll(db, fake)
    assert report.accepted == 2 and report.waiting == 1
    assert fake.flagged == ["1", "2"]
    assert _poll(db, fake).accepted == 1


def test_an_unreadable_message_does_not_cost_the_others(db, owner):
    user, _ = owner
    fake = FakeImap([_mail(message_id="<bad@x>"), _mail(message_id="<good@x>", body="Fine.")])
    real = echo_imap_service.parse_mail
    seen = []

    def parse(raw):
        seen.append(raw)
        if len(seen) == 1:
            raise ValueError("a body the parser chokes on")
        return real(raw)

    with patch.object(echo_imap_service, "parse_mail", parse):
        report = _poll(db, fake)
    assert report.unreadable == 1 and report.accepted == 1 and len(_shares(db, user)) == 1
    assert fake.flagged == ["1", "2"], "or a poison message would be fetched at every tick"


def test_a_store_failure_is_counted_rolled_back_and_retried(db, owner):
    user, _ = owner
    fake = FakeImap([_mail(message_id="<a@x>"), _mail(message_id="<b@x>", body="Second.")])
    real = echo_imap_service._store
    calls = []

    def store(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        return real(*a, **k)

    with patch.object(echo_imap_service, "_store", store):
        report = _poll(db, fake)
    assert report.failed == 1 and report.accepted == 1
    assert fake.flagged == ["2"], "still unread, so the next poll tries it"
    assert _poll(db, fake).accepted == 1 and len(_shares(db, user)) == 2


# ---------------------------------------------------------------------------
# Mail cannot teach the voice
# ---------------------------------------------------------------------------


def test_mail_never_reaches_voice_signals(db, owner):
    """Even from the owner's own address: anyone can write that From line."""
    user, _ = owner
    _poll(db, FakeImap([_mail(sender=OWNER, message_id="<own@x>")]))
    assert _shares(db, user) == [], "the tenant's address is not on the list by itself"

    _poll(db, FakeImap([_mail(body="I always end my sentences like this, friend.")]))
    share = _shares(db, user)[0]
    assert echo_processing_service.voice_eligible(share) is False
    inputs = echo_signal_extraction.gather_inputs(db, user.id)
    assert not [i for i in inputs if i.ref == f"share:{share.id}"]

    with patch.object(echo_signal_extraction, "maybe_queue") as queue, patch.object(
        echo_processing_service.echo_vectors, "upsert_share_vector", return_value="v"
    ):
        echo_processing_service.process_share(db, share.id)
    queue.assert_not_called()


def test_a_mail_share_cannot_be_marked_as_own_words(unauthenticated_client, db, owner):
    user, headers = owner
    _poll(db, FakeImap([_mail()]))
    share = _shares(db, user)[0]
    r = unauthenticated_client.patch(f"{SHARES}/{share.id}", json={"author_is_tenant": True}, headers=headers)
    assert r.status_code == 422 and "context only" in r.json()["detail"]
    db.refresh(share)
    assert share.author_is_tenant is False
    assert not [i for i in echo_signal_extraction.gather_inputs(db, user.id) if i.ref == f"share:{share.id}"]
    # The rest of the row stays the user's to edit.
    r = unauthenticated_client.patch(f"{SHARES}/{share.id}", json={"annotation": "Why I kept this"}, headers=headers)
    assert r.status_code == 200 and r.json()["user_annotation"] == "Why I kept this"


@pytest.mark.parametrize("field", ["text", "url"])
def test_no_client_can_create_an_own_words_mail_share(unauthenticated_client, db, owner, field):
    value = "Some words" if field == "text" else "https://example.org/a"
    body = {field: value, "surface": "email_in", "author_is_tenant": True}
    r = unauthenticated_client.post(SHARES, json=body, headers=owner[1])
    assert r.status_code == 422


def test_every_other_surface_still_marks_own_words(unauthenticated_client, db, owner):
    r = unauthenticated_client.post(
        SHARES, json={"text": "Mine", "surface": "manual_quick_share", "author_is_tenant": True}, headers=owner[1]
    )
    assert r.status_code == 201 and r.json()["author_is_tenant"] is True


# ---------------------------------------------------------------------------
# Nothing leaves in a log
# ---------------------------------------------------------------------------


def _logged(logger: MagicMock) -> str:
    return " ".join(repr(c) for c in logger.mock_calls)


def test_the_log_has_counts_and_no_mail(db, owner):
    fake = FakeImap(
        [
            _mail(subject="A private subject", body=BODY),
            _mail(sender="stranger@evil.example", message_id="<x@y>", subject="Another private subject"),
        ]
    )
    with patch.object(echo_imap_service, "logger") as logger:
        _poll(db, fake)
    text = _logged(logger)
    assert "accepted" in text
    for secret in (BODY, "private subject", ALLOWED, "stranger", "evil.example", PASSWORD, "<one@mail.example>"):
        assert secret not in text


def test_a_failed_poll_logs_the_type_of_failure_only(db, owner):
    def connect():
        raise imaplib.IMAP4.error(f"LOGIN failed: {PASSWORD} rejected for {ALLOWED}")

    with patch.object(echo_imap_service, "logger") as logger:
        report = echo_imap_service.poll(db, connect=connect)
    assert report.status == "error"
    text = _logged(logger)
    assert "error" in text and PASSWORD not in text and ALLOWED not in text
    assert not logger.exception.called, "a traceback would print the exception's text"


def test_the_connection_is_tls_with_the_certificate_verified(monkeypatch):
    monkeypatch.setattr(settings, "ECHO_IMAP_HOST", "imap.example.com")
    monkeypatch.setattr(settings, "ECHO_IMAP_USERNAME", "inbox@example.com")
    monkeypatch.setattr(settings, "ECHO_IMAP_PASSWORD", PASSWORD)
    with patch.object(echo_imap_service.imaplib, "IMAP4_SSL") as tls:
        client = echo_imap_service._connect()
    args, kwargs = tls.call_args
    assert args == ("imap.example.com", 993)
    assert kwargs["ssl_context"].verify_mode == ssl.CERT_REQUIRED and kwargs["ssl_context"].check_hostname
    assert kwargs["timeout"] > 0
    client.login.assert_called_once_with("inbox@example.com", PASSWORD)


def test_a_refused_login_hangs_up(monkeypatch):
    with patch.object(echo_imap_service.imaplib, "IMAP4_SSL") as tls:
        tls.return_value.login.side_effect = imaplib.IMAP4.error("no")
        with pytest.raises(imaplib.IMAP4.error):
            echo_imap_service._connect()
    tls.return_value.logout.assert_called_once_with()


def test_a_folder_name_is_quoted(db, owner, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_IMAP_FOLDER", 'To "Echo"')
    fake = FakeImap([])
    _poll(db, fake)
    assert fake.selected == r'"To \"Echo\""'


# ---------------------------------------------------------------------------
# Who it polls for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["ECHO_IMAP_HOST", "ECHO_IMAP_USERNAME", "ECHO_IMAP_PASSWORD"])
def test_a_half_configured_mailbox_is_not_opened(db, owner, monkeypatch, name):
    monkeypatch.setattr(settings, name, "")
    connect = MagicMock()
    assert echo_imap_service.poll(db, connect=connect).status == "unconfigured"
    connect.assert_not_called()


def test_off_means_the_mailbox_is_not_opened(db, owner, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_IMAP_ENABLED", False)
    connect = MagicMock()
    assert echo_imap_service.poll(db, connect=connect).status == "disabled"
    connect.assert_not_called()


def test_an_address_with_no_account_is_not_polled(db, owner, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_IMAP_TENANT_EMAIL", "nobody@example.com")
    connect = MagicMock()
    assert echo_imap_service.poll(db, connect=connect).status == "no_tenant"
    connect.assert_not_called()


def test_the_tier_gate_matches_the_share_intake(db, owner):
    """Checked on every poll, like a share token on every use."""
    user, _ = owner
    user.tier = "pro"
    db.commit()
    connect = MagicMock()
    assert echo_imap_service.poll(db, connect=connect).status == "not_entitled"
    connect.assert_not_called()


# ---------------------------------------------------------------------------
# The tick
# ---------------------------------------------------------------------------


def test_one_beat_entry_with_the_inbox_on(owner):
    assert set(_beat_schedule()) == {"scheduler-tick"}


def test_the_tick_polls_the_mailbox_end_to_end(unauthenticated_client, db, owner):
    """The whole production path: the tick arms the row and dispatches the
    kind on the tenant's queue, and the task it dispatched stores the mail."""
    user, headers = owner
    user_id = user.id  # the tick's session closes under this object
    assert echo_imap_service.KIND in scheduler_service.registered_kinds()

    with patch.object(scheduler_tasks, "SessionLocal", return_value=db), patch(
        "app.services.task_routing_service.dispatch_for_tenant_id"
    ) as dispatch:
        scheduler_tasks.scheduler_tick.run()
    task, _db, tenant_id, *args = dispatch.call_args.args
    assert task.name == "echo.poll_imap" and tenant_id == user_id and args == [echo_imap_service.TARGET]

    fake = FakeImap([_mail()])
    with patch.object(echo_tasks, "SessionLocal", return_value=db), patch.object(
        echo_imap_service, "_connect", return_value=fake
    ):
        status = echo_tasks.poll_imap_task.run(*args, **dispatch.call_args.kwargs)
    assert status == "ok"
    items = unauthenticated_client.get(SHARES, headers=headers).json()["items"]
    assert [i["surface"] for i in items] == ["email_in"]


def test_the_tick_keeps_the_row_and_does_not_rearm_it(db, owner, monkeypatch):
    with patch.object(scheduler_tasks, "SessionLocal", return_value=db), patch(
        "app.services.task_routing_service.dispatch_for_tenant_id"
    ) as dispatch:
        scheduler_tasks.scheduler_tick.run()
        next_run = db.query(ScheduledRun).filter_by(kind="echo_imap").one().next_run_at
        assert next_run > scheduler_service.utcnow(), "advanced past now by the dispatch"
        scheduler_tasks.scheduler_tick.run()
    assert dispatch.call_count == 1, "not due again until the next interval"
    run = db.query(ScheduledRun).filter_by(kind="echo_imap").one()
    assert run.next_run_at == next_run
    assert json.loads(run.cadence_json) == {"cadence": "every", "seconds": settings.SCHEDULER_TICK_SECONDS}


def test_turning_the_inbox_off_removes_the_row(db, owner, monkeypatch):
    echo_imap_service.sync_schedule(db)
    assert db.query(ScheduledRun).filter_by(kind="echo_imap").count() == 1
    monkeypatch.setattr(settings, "ECHO_IMAP_ENABLED", False)
    with patch.object(scheduler_tasks, "SessionLocal", return_value=db), patch(
        "app.services.task_routing_service.dispatch_for_tenant_id"
    ) as dispatch:
        scheduler_tasks.scheduler_tick.run()
    assert db.query(ScheduledRun).filter_by(kind="echo_imap").count() == 0
    dispatch.assert_not_called()


def test_off_by_default_the_tick_adds_no_row(db):
    assert settings.ECHO_IMAP_ENABLED is False
    echo_imap_service.sync_schedule(db)
    assert db.query(ScheduledRun).filter_by(kind="echo_imap").count() == 0


def test_a_new_tenant_address_moves_the_row(db, owner, monkeypatch):
    echo_imap_service.sync_schedule(db)
    other, _ = _studio(db, "other-owner@example.com")
    monkeypatch.setattr(settings, "ECHO_IMAP_TENANT_EMAIL", "other-owner@example.com")
    echo_imap_service.sync_schedule(db)
    assert db.query(ScheduledRun).filter_by(kind="echo_imap").one().tenant_id == other.id


def test_a_broken_sync_does_not_stop_the_tick(db, owner):
    with patch.object(scheduler_tasks, "SessionLocal", return_value=db), patch.object(
        echo_imap_service, "sync_schedule", side_effect=RuntimeError("boom")
    ), patch.object(scheduler_tasks.scheduler_service, "run_tick", return_value={"dispatched": 0}) as run:
        out = scheduler_tasks.scheduler_tick.run()
    run.assert_called_once_with(db)
    assert out == {"dispatched": 0}


# ---------------------------------------------------------------------------
# The real imaplib, over a socket
# ---------------------------------------------------------------------------


class _ScriptedImap(socketserver.StreamRequestHandler):
    """Just enough of an IMAP server for imaplib's own parser: what the fake
    assumes about imaplib's answers, proved against imaplib. Message 9 puts
    its data items after the literal, which servers may do."""

    def handle(self):
        server = self.server
        out = self.wfile.write
        out(b"* OK scripted server ready\r\n")
        for line in self.rfile:
            tag, _, rest = line.decode("ascii").strip().partition(" ")
            done = f"{tag} OK done\r\n".encode()
            upper = rest.upper()
            if upper.startswith("CAPABILITY"):
                out(b"* CAPABILITY IMAP4rev1\r\n" + done)
            elif upper.startswith("LOGIN"):
                out(done)
            elif upper.startswith("SELECT"):
                out(b"* 2 EXISTS\r\n* 0 RECENT\r\n* OK [PERMANENTFLAGS (\\Seen)] flags\r\n")
                out(f"{tag} OK [READ-WRITE] selected\r\n".encode())
            elif upper.startswith("UID SEARCH"):
                out(b"* SEARCH " + " ".join(str(u) for u in sorted(server.messages)).encode() + b"\r\n" + done)
            elif upper.startswith("UID FETCH"):
                uid = int(rest.split()[2])
                raw = server.messages[uid]
                head = raw.split(b"\n\n", 1)[0] + b"\n\n" if b"\r\n\r\n" not in raw else raw.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
                if "HEADER" in upper:
                    if uid == 9:
                        out(f"* 2 FETCH (BODY[HEADER] {{{len(head)}}}\r\n".encode() + head + f" UID {uid} RFC822.SIZE {len(raw)})\r\n".encode())
                    else:
                        out(f"* 1 FETCH (UID {uid} RFC822.SIZE {len(raw)} BODY[HEADER] {{{len(head)}}}\r\n".encode() + head + b")\r\n")
                else:
                    out(f"* 1 FETCH (UID {uid} BODY[] {{{len(raw)}}}\r\n".encode() + raw + b")\r\n")
                out(done)
            elif upper.startswith("UID STORE"):
                server.stores.append(rest)
                out(done)
            elif upper.startswith("LOGOUT"):
                out(b"* BYE bye\r\n" + done)
                return
            else:
                out(f"{tag} BAD unknown\r\n".encode())


def test_the_poller_against_the_real_imaplib(db, owner):
    user, _ = owner
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _ScriptedImap)
    server.daemon_threads = True
    server.messages = {7: _mail(), 9: _mail(message_id="<two@x>", body="Second message.")}
    server.stores = []
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def connect():
        client = imaplib.IMAP4("127.0.0.1", server.server_address[1], timeout=5)
        client.login("inbox@example.com", PASSWORD)
        return client

    try:
        report = echo_imap_service.poll(db, connect=connect)
    finally:
        server.shutdown()
        server.server_close()
    assert report.status == "ok" and report.accepted == 2, report
    texts = sorted(s.extracted_text.strip() for s in _shares(db, user))
    assert texts == sorted([BODY, "Second message."])
    assert [s.split()[2] for s in server.stores] == ["7", "9"]
    assert all(re.search(r"\+FLAGS\.SILENT \(\\Seen\)", s) for s in server.stores)
