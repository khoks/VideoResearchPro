"""T-4.11.4.4 at each changed call site: a warning or error the API writes
names no user's words, no address and no credential, and still says what
happened.

Each test patches the module's logger and reads every call's arguments
(``said``), so a word that reached a line in its format string or as an
argument is caught. The failures are built the way the real ones read: a
database error quotes its statement's values, a parser quotes what it could
not read, and a model's score written as words reaches ``float()``.
``tests/test_routers/test_api_log_words.py`` runs an Echo import and a draft
through their routes and reads what a real handler wrote.

Raise statements here name constants, never literals: ``traceback_without_text``
keeps each frame's source line, and a literal in it would be read as a leak.
"""
from __future__ import annotations

import io
import json
import sqlite3
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError

import app.main as main_module
from app.agents import echo_agent, knowledge_agent, qa_agent
from app.config import settings
from app.connectors import registry
from app.connectors.archive import ExportUnreadable, ImportPreview
from app.connectors.base import ImportedShare
from app.models.echo_connector import EchoConnectorGrant
from app.models.job import Job
from app.models.share import Share
from app.routers import auth as auth_router
from app.routers import qa as qa_router
from app.services import (
    activity_event_service,
    audit_service,
    auth_service,
    echo_import_service,
    echo_processing_service,
    echo_vectors,
    note_service,
)
from app.services import echo_connector_service as echo_svc
from app.services import echo_signal_extraction as signals_ex
from app.services import echo_voice_test_service as vt
from app.utils.shared_url_log import exception_kind, loggable_filename
from tests.test_services.test_worker_log_call_sites import said

# The user's words, an address and a file name: distinctive enough to find.
WORDS = "Zanzibar quokka fermentation"
ADDRESS = "wombat.ops@zanzibar.org"
FILENAME = "WhatsApp Chat with Xylophone Wombat.wchat"
PASSWORD = "Quokka-Xylophone-77!"
STORED_HASH = "$2b$12$WombatHashWombatHashWombatHashWombatHashWombatHa"
FORBIDDEN = ("zanzibar", "quokka", "fermentation", "wombat", "xylophone")


def assert_no_words(logger: MagicMock, *also: str) -> str:
    text = said(logger)
    assert text, "nothing was logged, so nothing was checked"
    for word in (*FORBIDDEN, *also):
        assert word.lower() not in text, f"{word!r} reached a log line:\n{text}"
    return text


def db_error(*params, cls=OperationalError, cause="database is locked"):
    """A database error as SQLAlchemy builds one: its text quotes the
    statement and every bound value."""
    error = cls("INSERT INTO t (a, b) VALUES (?, ?)", params, sqlite3.OperationalError(cause))
    assert str(params[0]) in str(error), "the error must quote its values for the test to mean anything"
    return error


@pytest.fixture
def log(monkeypatch):
    """A patched logger for one module: ``log(module)``."""
    def patch_module(module):
        fake = MagicMock()
        monkeypatch.setattr(module, "logger", fake)
        return fake

    return patch_module


# ---------------------------------------------------------------------------
# The helpers
# ---------------------------------------------------------------------------

def test_a_file_name_is_named_by_its_extension_and_length():
    assert loggable_filename(FILENAME) == f"a .wchat file name of {len(FILENAME)} characters"
    assert loggable_filename("C:\\Users\\me\\Asha.TXT") == "a .txt file name of 20 characters"
    assert loggable_filename("no-extension") == "a file name of 12 characters with no extension"
    assert loggable_filename(None) == "a file name of 0 characters with no extension"


def test_an_exception_is_named_by_its_type_and_any_status():
    class RateLimitError(Exception):
        status_code = 429

    class HTTPStatusError(Exception):
        response = SimpleNamespace(status_code=503)

    assert exception_kind(RateLimitError(WORDS)) == "RateLimitError (HTTP 429)"
    assert exception_kind(HTTPStatusError(WORDS)) == "HTTPStatusError (HTTP 503)"
    assert exception_kind(ValueError(WORDS)) == "ValueError"
    assert exception_kind(MagicMock(side_effect=ValueError)) == "MagicMock", "a mock's attribute is not a status"


def test_an_address_is_masked_to_its_first_letters_and_top_level_domain():
    assert auth_service.masked_email("boss@example.com") == "b***@e***.com"
    assert auth_service.masked_email(ADDRESS) == "w***@z***.org"
    assert auth_service.masked_email("ops@mail.example.co.uk") == "o***@m***.uk"
    assert auth_service.masked_email("root@localhost") == "r***@l***"
    assert auth_service.masked_email("not-an-address") == "n***"


# ---------------------------------------------------------------------------
# Auth: the operator list, a password check, a registration, the audit log
# ---------------------------------------------------------------------------

class _Borrowed:
    """The test's session, lent to code that closes what it opens."""

    def __init__(self, db):
        self._db = db

    def query(self, *args, **kwargs):
        return self._db.query(*args, **kwargs)

    def close(self):
        pass


def test_an_unregistered_operator_is_named_by_place_and_mask(db, log, monkeypatch):
    auth_service.create_user(db, email="boss@example.com", password="pw" * 6)
    monkeypatch.setattr(settings, "ADMIN_EMAILS", f"boss@example.com, {ADDRESS.upper()}, quokka@example.com,")
    fake = log(auth_service)

    missing = auth_service.warn_unregistered_operators(session_factory=lambda: _Borrowed(db))

    assert missing == ["quokka@example.com", ADDRESS], "the caller still gets the addresses"
    text = assert_no_words(fake, ADDRESS, "quokka@example.com", "boss@example.com")
    lines = [str(c.args[0]) % c.args[1:] for c in fake.warning.call_args_list]
    assert len(lines) == 2
    assert lines[0].startswith("ADMIN_EMAILS entry 2 of 3 (w***@z***.org) names no account.")
    assert lines[1].startswith("ADMIN_EMAILS entry 3 of 3 (q***@e***.com) names no account.")
    assert "register the account before listing it" in text


def test_a_failed_operator_check_at_startup_names_no_address(monkeypatch):
    fake = MagicMock()
    with (
        patch.object(main_module, "logger", fake),
        patch.object(main_module.auth_service, "warn_unregistered_operators", side_effect=db_error(ADDRESS)),
    ):
        with TestClient(main_module.app):
            pass

    lines = [c for c in fake.method_calls if "ADMIN_EMAILS" in str(c.args[:1])]
    assert len(lines) == 1 and lines[0][0] == "error", fake.method_calls
    text = " ".join(str(c.args[0]) % tuple(c.args[1:]) for c in lines).lower()
    assert ADDRESS not in text and "zanzibar" not in text
    assert "operationalerror" in text and "continuing startup" in text


def test_a_password_check_that_raises_names_neither_password_nor_hash(log, monkeypatch):
    fake = log(auth_service)
    hashing = MagicMock()
    hashing.verify.side_effect = ValueError(f"malformed hash {STORED_HASH} for {PASSWORD}")
    monkeypatch.setattr(auth_service, "_pwd_context", hashing)

    assert auth_service.verify_password(PASSWORD, STORED_HASH) is False

    text = assert_no_words(fake, PASSWORD.lower(), STORED_HASH.lower())
    assert fake.error.called and not fake.exception.called
    assert "password verification failed" in text and "valueerror" in text


def test_a_registration_that_loses_its_race_names_no_address_or_hash(unauthenticated_client, log, monkeypatch):
    fake = log(auth_router)
    raced = db_error(ADDRESS, STORED_HASH, cls=IntegrityError, cause="UNIQUE constraint failed: users.email")
    monkeypatch.setattr(auth_router.auth_service, "create_user", MagicMock(side_effect=raced))

    r = unauthenticated_client.post("/api/v1/auth/register", json={"email": ADDRESS, "password": PASSWORD})

    assert r.status_code == 409
    text = assert_no_words(fake, STORED_HASH.lower(), PASSWORD.lower())
    assert "failed to create user due to integrity error" in text and "integrityerror" in text


def test_a_failed_audit_write_names_no_address_or_question(log):
    fake = log(audit_service)
    db = MagicMock()
    db.commit.side_effect = db_error(json.dumps({"email": ADDRESS, "question": WORDS}))

    row = audit_service.record(
        db, event=audit_service.Event.LOGIN_FAILURE, user_id="u-1",
        ip_address="203.0.113.9", metadata={"email": ADDRESS, "question": WORDS},
    )

    assert row is None and db.rollback.called
    text = assert_no_words(fake, "203.0.113.9")
    assert "failed to persist event=" in text and "user_id=u-1" in text and "operationalerror" in text


# ---------------------------------------------------------------------------
# Echo imports: an importer's failure, the registry, a run that stops
# ---------------------------------------------------------------------------

class _Importer:
    """A registered importer whose parts fail the way a parser does, quoting
    the file it reads."""

    display_name = "Words test"
    privacy_weight = "high"
    consent_disclosure = "test"

    def __init__(self, name, *, accepts=False, sniff_fails=False, accepts_fails=False, parse_fails=False):
        self.name = name
        self._accepts, self._sniff_fails = accepts, sniff_fails
        self._accepts_fails, self._parse_fails = accepts_fails, parse_fails

    def accepts(self, filename):
        if self._accepts_fails:
            raise ValueError(f"cannot tell the export from its name {filename!r}")
        return self._accepts and filename.endswith(".wchat")

    def sniff(self, source):
        if self._sniff_fails:
            source.fileobj.seek(0)
            first = source.fileobj.readline().decode("utf-8")
            raise ValueError(f"time data {first!r} does not match format")
        return False

    def preview(self, source, options):
        return ImportPreview(importer=self.name, label=self.display_name, summary={"messages": 2})

    def parse(self, source, *, tenant_id, options=None, filename=None, stats=None):
        source.fileobj.seek(0)
        lines = source.fileobj.read().decode("utf-8").splitlines()
        yield ImportedShare(external_id="1", occurred_at=echo_import_service._now(), text=lines[0])
        if self._parse_fails:
            raise ValueError(f"invalid literal for int() with base 10: {lines[1]!r}")


CONTENT = f"12/31/24, 9:00 - Asha: {WORDS}\nwombat line two\n".encode()


@pytest.fixture
def importers():
    made = []

    def register(*items):
        for item in items:
            registry.register_importer(item)
            made.append(item.name)

    registry.load_builtin()
    yield register
    for name in made:
        registry.unregister_importer(name)


def test_an_importer_that_fails_to_sniff_names_the_file_by_kind(log, importers):
    fake = log(echo_import_service)
    importers(_Importer("aaa_words_sniff", sniff_fails=True))
    source = echo_import_service._source(io.BytesIO(CONTENT), FILENAME)

    with pytest.raises(ExportUnreadable):
        echo_import_service._importer(source, None)

    text = assert_no_words(fake, FILENAME.lower(), "12/31/24")
    assert f"importer aaa_words_sniff failed to sniff a .wchat file name of {len(FILENAME)} characters" in text
    assert "valueerror" in text and not fake.exception.called


def test_an_importer_whose_accepts_raises_names_the_file_by_kind(log, importers):
    fake = log(registry)
    importers(_Importer("aaa_words_accepts", accepts_fails=True), _Importer("zzz_words", accepts=True))

    assert registry.importer_for(FILENAME).name == "zzz_words", "a failing importer is skipped"

    text = assert_no_words(fake, FILENAME.lower())
    assert f"importer aaa_words_accepts failed on accepts(a .wchat file name of {len(FILENAME)} characters)" in text
    assert "valueerror" in text and not fake.exception.called


def test_an_import_that_stops_is_logged_by_its_frames_and_raised_in_words(db, log, importers):
    fake = log(echo_import_service)
    importers(_Importer("zzz_words_run", accepts=True, parse_fails=True))
    user = auth_service.create_user(db, email=f"imp-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)

    with pytest.raises(echo_import_service.ImportStopped) as stopped:
        echo_import_service.run_import(db, user, io.BytesIO(CONTENT), FILENAME, importer="zzz_words_run")

    assert str(stopped.value) == "Import stopped: ValueError"
    text = assert_no_words(fake, FILENAME.lower())
    assert "failed after 1 shares" in text and "valueerror" in text and not fake.exception.called
    db.expire_all()
    record = db.query(echo_import_service.EchoImport).filter_by(tenant_id=user.id).one()
    assert record.status == "failed" and record.error == "Import stopped: ValueError"


# ---------------------------------------------------------------------------
# Echo: a draft's classify and critique, signals, the voice test
# ---------------------------------------------------------------------------

def test_a_drafts_classify_and_critique_failures_are_named_by_kind(log):
    from tests.test_services.test_echo_draft import deps

    fake = log(echo_agent)
    critique = {"tone": WORDS, "vocabulary": 4, "structure": 4, "topicality": 4, "grounded": 4, "notes": []}
    d, _ = deps(
        classify=RuntimeError(f"local server echoed the request: {WORDS}"),
        drafts=[f"{WORDS} [S1]."],
        critiques=[critique],
    )

    state = echo_agent.run_echo_draft(d, message=f"Who pays for the {WORDS}?")

    assert state["result"]["draft"] == f"{WORDS}.", "the draft itself is unaffected"
    text = assert_no_words(fake)
    assert "echo draft: classify failed (runtimeerror); drafting without its reading" in text
    assert "echo draft: critique failed (valueerror); the draft keeps no scores" in text


def _studio(db):
    user = auth_service.create_user(db, email=f"echo-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()
    return user


def _note(db, user, body):
    job = Job(tenant_id=user.id, job_type="topic", topic="t", status="completed")
    db.add(job)
    db.commit()
    return note_service.create_note(db, user.id, target_type="job", target_id=job.id, body_md=body)


def test_a_failed_signals_batch_is_named_by_kind(db, log):
    fake = log(signals_ex)
    user = _studio(db)
    _note(db, user, f"My own words about {WORDS}, written plainly.")

    def llm(prompt):
        raise RuntimeError(f"local server echoed the request: {prompt}")

    report = signals_ex.run(db, user.id, llm=llm, model="m")

    assert report.calls_failed == 1
    text = assert_no_words(fake)
    assert "batch of 1 failed for tenant" in text and "(runtimeerror)" in text


def test_an_inline_extraction_that_fails_is_logged_by_its_frames(db, log, monkeypatch):
    fake = log(signals_ex)
    user = _studio(db)
    monkeypatch.setattr(settings, "ECHO_SIGNAL_EXTRACTION", "inline")
    monkeypatch.setattr(settings, "ECHO_SIGNALS_MIN_NEW_INPUTS", 0)
    monkeypatch.setattr(signals_ex, "run", MagicMock(side_effect=db_error(WORDS)))

    assert signals_ex.maybe_queue(db, user.id) == "queue_failed"

    text = assert_no_words(fake)
    assert "could not queue or run extraction" in text and "operationalerror" in text
    assert not fake.exception.called


def test_a_voice_test_retry_is_named_by_kind(db, log, monkeypatch):
    from langchain_core.messages import AIMessage

    fake = log(vt)
    replies = [RuntimeError(f"local server echoed the request: {WORDS}"), "a draft"]

    class Client:
        def invoke(self, messages):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return AIMessage(content=reply)

    monkeypatch.setattr("app.services.llm_service.get_llm_for", lambda *a, **kw: Client())
    monkeypatch.setattr(vt.time, "sleep", lambda s: None)

    assert vt._drafter(db, "tenant-1")("p")[0] == "a draft"

    text = assert_no_words(fake)
    assert "voice test: retry after runtimeerror" in text


def test_a_voice_test_that_cannot_be_written_is_logged_by_its_frames(db, log):
    from tests.test_services.test_echo_voice_test import _generating, _writer

    fake = log(vt)
    user = _writer(db)
    row = _generating(db, user)
    failure = db_error(WORDS)

    def ask(prompt):
        raise failure

    vt.generate(db, row.id, ask=ask)

    db.refresh(row)
    assert row.status == "failed"
    text = assert_no_words(fake)
    assert f"voice test: could not write {row.id}" in text and "operationalerror" in text
    assert not fake.exception.called


# ---------------------------------------------------------------------------
# Echo shares and connectors
# ---------------------------------------------------------------------------

def _share(db, user):
    share = Share(
        tenant_id=user.id, user_id=user.id, surface="web", content_type="text",
        raw_payload_json=json.dumps({"kind": "text", "text": WORDS}), extracted_text=WORDS,
    )
    db.add(share)
    db.commit()
    return share


def test_a_share_that_fails_to_process_is_logged_by_its_frames(db, log, monkeypatch):
    fake = log(echo_processing_service)
    share = _share(db, _studio(db))
    failure = RuntimeError(f"could not read https://example.org/private?token=abc while reading {WORDS}")

    def broken(share_, payload):
        raise failure

    monkeypatch.setattr(echo_processing_service, "_process_text", broken)

    outcome = echo_processing_service.process_share(db, share.id)

    assert outcome.state == "failed"
    text = assert_no_words(fake, "token=abc", "/private")
    assert f"echo: processing share {share.id} failed" in text and "runtimeerror" in text
    assert not fake.exception.called


def test_a_share_event_that_cannot_be_recorded_names_no_title(db, log, monkeypatch):
    fake = log(echo_processing_service)
    share = _share(db, _studio(db))
    monkeypatch.setattr(
        echo_processing_service, "_process_text",
        lambda share_, payload: (WORDS, {"extractor": "as_is", "title": f"{WORDS} notes"}),
    )
    monkeypatch.setattr(echo_vectors, "upsert_share_vector", lambda *a, **kw: "vector-1")
    monkeypatch.setattr(activity_event_service, "record_share_event", MagicMock(side_effect=db_error(f"{WORDS} notes")))

    outcome = echo_processing_service.process_share(db, share.id)

    assert outcome.state == "processed"
    text = assert_no_words(fake)
    assert f"could not record the share event for {share.id}" in text and "operationalerror" in text


def test_a_connector_sync_that_crashes_names_no_event(db, log, monkeypatch):
    from app.connectors.base import ConnectorTokens
    from app.connectors.github.connector import GitHubConnector

    fake = log(echo_svc)
    connector = GitHubConnector(request=lambda *a, **kw: pytest.fail("no request"))
    connector.name = "github_crash_words"
    connector.incremental_sync = lambda ctx, since: iter([])
    monkeypatch.setattr(echo_svc.activity_event_service, "store_events", MagicMock(side_effect=db_error(WORDS)))
    registry.register_connector(connector)
    tenant = str(uuid.uuid4())
    try:
        echo_svc._store_tokens(db, tenant, connector.name, ConnectorTokens(access_token="gh", account_label="x"))
        grant = EchoConnectorGrant(tenant_id=tenant, connector=connector.name, consent_version="v",
                                   backfilled_at=echo_svc._now(), account_label="x")
        db.add(grant)
        db.commit()
        outcome = echo_svc.run_sync(db, grant.id)
    finally:
        registry.unregister_connector(connector.name)

    assert outcome.status == "error"
    text = assert_no_words(fake)
    assert "sync crashed for grant" in text and "operationalerror" in text


# ---------------------------------------------------------------------------
# Author Studio, generated inline by `POST /author/outputs?sync=true`
# ---------------------------------------------------------------------------

def test_an_unexpected_generation_failure_is_logged_by_its_frames(db, log, monkeypatch):
    from app.services import output_service
    from app.services.outputters.deck import DeckOutputter

    fake = log(output_service)
    user = _studio(db)
    failure = db_error(f"{WORDS}: the deck's text")

    def explode(self, db_, user_, output):
        raise failure

    monkeypatch.setattr(DeckOutputter, "generate", explode)
    row = output_service.create_output(db, user_id=user.id, kind="deck", title=f"My {WORDS} deck", source_ids=["j"])

    out = output_service.run_generation(db, user, row)

    assert out.status == "failed" and WORDS in out.error_message, "the owner's row keeps the words"
    text = assert_no_words(fake)
    assert f"unexpected generation failure for output_id={row.id} kind=deck" in text and "operationalerror" in text
    assert not fake.exception.called


# ---------------------------------------------------------------------------
# Q&A and knowledge
# ---------------------------------------------------------------------------

def test_a_streamed_answer_that_fails_is_logged_by_its_frames(client, db, test_user, log, monkeypatch):
    fake = log(qa_router)
    job = Job(job_type="topic", topic="t", status="completed", num_videos=1, tenant_id=test_user.id)
    db.add(job)
    db.commit()
    failure = db_error(WORDS, "the answer")

    def broken(*args, **kwargs):
        raise failure

    monkeypatch.setattr(qa_router, "_run_qa_and_persist", broken)

    r = client.post(f"/api/v1/jobs/{job.id}/qa/stream", json={"question": WORDS})

    assert r.status_code == 200 and '"type": "error"' in r.text
    text = assert_no_words(fake)
    assert f"streaming q&a failed for job {job.id}" in text and "operationalerror" in text
    assert not fake.exception.called


def test_a_fabricated_citation_is_named_by_its_lengths(log):
    fake = log(qa_agent)
    title, channel = f"The {WORDS} question", "Wombat Channel"
    answer = f'It is so [Source: "{title}" by {channel} at 1:00].'

    sanitized, removed = qa_agent._sanitize_citations(answer, [{"metadata": {"video_title": "Real", "channel_name": "Real"}}])

    assert removed == 1 and "[Source: unverified]" in sanitized
    text = assert_no_words(fake)
    assert f"a title of {len(title)} characters, a channel of {len(channel)}" in text


def test_a_knowledge_reply_that_is_not_json_is_named_by_its_length(log):
    fake = log(knowledge_agent)
    reply = f"Here is what the PDF says about {WORDS}: not JSON at all"

    parsed = knowledge_agent._parse_extraction(reply)

    assert parsed == {k: [] for k in knowledge_agent._KNOWLEDGE_KEYS}
    text = assert_no_words(fake)
    assert f"returned non-json of {len(reply)} characters" in text
