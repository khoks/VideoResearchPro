"""T-4.11.4.4: the API's log holds no user's words, read where it is written.

Two requests through their routes, with a handler on the root logger at INFO,
as ``LOG_FORMAT=json`` or any process that gives root a handler writes them,
with the record factory of D-151 and a formatter that renders tracebacks:

- ``POST /echo/import/preview`` and ``POST /echo/import`` with an export
  named after the person it is with. One importer's ``accepts`` and another's
  ``sniff`` fail quoting the file name and its first line, and the import's
  parse stops on a line it quotes. The run answers in words (500, "Import
  stopped: ValueError"), so nothing reaches the server's own log of an
  unhandled exception.
- The same two routes when the importer's preview fails on a line it
  quotes (review of #447): both answer 500, "Preview stopped: ValueError".
- ``POST /echo/draft`` with an incoming message. The classifier's model
  fails, quoting the request back as a local server can, and the critique's
  model writes a score as the draft's words, which ``float()`` quotes.

None of the words may be in what the handler wrote. They stay where the user
reads them: the import's row and the draft. A mutation puts one call site
back and shows the check sees the leak.
"""
from __future__ import annotations

import io
import json
import logging
import traceback

import pytest

from app.agents import echo_agent
from app.connectors import registry
from app.services import echo_import_service
from tests.test_routers.test_echo_drafts import DRAFT, _enable, _user
from tests.test_routers.test_echo_imports import _studio
from tests.test_services.test_api_log_call_sites import _Importer

PERSON = "Xylophone Wombat"
FILENAME = f"WhatsApp Chat with {PERSON}.wchat"
FIRST_LINE = "12/31/24, 9:00 - Asha: the Zanzibar quokka plan"
CONTENT = f"{FIRST_LINE}\nfermentation starts at dawn\n".encode()
MESSAGE = "Zanzibar quokka asks who pays the tariff"
DRAFT_WORDS = "Fermentation xylophones pay first"
FORBIDDEN = ("zanzibar", "quokka", "fermentation", "wombat", "xylophone", "12/31/24")


@pytest.fixture
def api_log():
    """What a root handler at INFO writes, tracebacks included."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(level)


def assert_nothing_said(stream: io.StringIO, *also: str) -> str:
    text = stream.getvalue()
    lowered = text.lower()
    for word in (*FORBIDDEN, *also):
        assert word.lower() not in lowered, f"{word!r} reached the API's log:\n{text}"
    return text


@pytest.fixture
def words_importers():
    registry.load_builtin()
    made = [
        _Importer("aaa_words_accepts", accepts_fails=True),
        _Importer("aab_words_sniff", sniff_fails=True),
        _Importer("zzz_words_chat", accepts=True, parse_fails=True),
    ]
    for importer in made:
        registry.register_importer(importer)
    yield
    for importer in made:
        registry.unregister_importer(importer.name)


def _upload(client, path, headers):
    return client.post(path, headers=headers, files={"file": (FILENAME, CONTENT, "text/plain")})


def _import_fails(client, db, headers):
    preview = _upload(client, "/api/v1/echo/import/preview", headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["importer"] == "zzz_words_chat", "chosen by name once the others failed"

    stopped = _upload(client, "/api/v1/echo/import", headers)
    assert stopped.status_code == 500, stopped.text
    assert stopped.json() == {"detail": "Import stopped: ValueError"}


def test_an_echo_import_that_fails_writes_none_of_the_users_words(unauthenticated_client, db, words_importers, api_log):
    user, headers = _studio(db, "log-words-import@example.com")

    _import_fails(unauthenticated_client, db, headers)

    text = assert_nothing_said(api_log, FILENAME, FIRST_LINE)
    assert "failed on accepts(a .wchat file name of" in text
    assert "importer aab_words_sniff failed to sniff a .wchat file name of" in text
    assert "failed after 1 shares" in text and "ValueError" in text
    record = db.query(echo_import_service.EchoImport).filter_by(tenant_id=user.id).one()
    assert record.status == "failed" and record.filename == FILENAME, "the row keeps the name its owner gave it"


def test_the_import_check_sees_a_leak(unauthenticated_client, db, words_importers, api_log, monkeypatch):
    """The mutation: the run's call site back to the whole traceback, and
    the same request writes the file's words. So the check above can fail."""
    monkeypatch.setattr(
        echo_import_service, "traceback_without_text", lambda e: "".join(traceback.format_exception(e))
    )
    _, headers = _studio(db, "log-words-mutant@example.com")

    _import_fails(unauthenticated_client, db, headers)

    assert "fermentation starts at dawn" in api_log.getvalue()


@pytest.fixture
def failing_models(monkeypatch):
    """The draft's models, faked as ``test_echo_drafts`` fakes them: the
    classifier fails quoting its prompt, the critique scores in words."""
    from app.services import echo_draft_service
    from tests.test_services.test_echo_draft import deps

    critique = {"tone": DRAFT_WORDS, "vocabulary": 4, "structure": 4, "topicality": 4, "grounded": 4, "notes": []}

    def make(db, user):
        d, _ = deps(
            classify=RuntimeError(f"local server echoed the request: {MESSAGE}"),
            drafts=[f"{DRAFT_WORDS} [S1]."],
            critiques=[critique],
        )
        return d

    monkeypatch.setattr(echo_draft_service, "_real_deps", make)


def _draft(client, db, monkeypatch):
    user, headers = _user(db)
    _enable(db, user, monkeypatch)
    r = client.post(DRAFT, json={"message": MESSAGE}, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["draft"] == f"{DRAFT_WORDS}.", "the draft is the user's to read"
    return r.json()


def test_a_drafts_failed_checks_write_none_of_the_words(unauthenticated_client, db, failing_models, api_log, monkeypatch):
    body = _draft(unauthenticated_client, db, monkeypatch)

    text = assert_nothing_said(api_log)
    assert "echo draft: classify failed (RuntimeError)" in text
    assert "echo draft: critique failed (ValueError)" in text
    assert body["voice_match_score"] in (None, 0, 0.0), "the critique did not score it"


def test_the_draft_check_sees_a_leak(unauthenticated_client, db, failing_models, api_log, monkeypatch):
    """The mutation: the critique's line back to the exception's text."""
    monkeypatch.setattr(echo_agent, "exception_kind", str)

    _draft(unauthenticated_client, db, monkeypatch)

    assert DRAFT_WORDS.lower() in api_log.getvalue().lower()


@pytest.fixture
def preview_importer():
    registry.load_builtin()
    importer = _Importer("zzz_words_preview", accepts=True, preview_fails=True)
    registry.register_importer(importer)
    yield
    registry.unregister_importer(importer.name)


def _previews_fail(client, headers):
    for path in ("/api/v1/echo/import/preview", "/api/v1/echo/import"):
        r = _upload(client, path, headers)
        assert r.status_code == 500, (path, r.text)
        assert r.json() == {"detail": "Preview stopped: ValueError"}, path


def test_a_preview_that_fails_writes_none_of_the_users_words(unauthenticated_client, db, preview_importer, api_log):
    user, headers = _studio(db, "log-words-preview@example.com")

    _previews_fail(unauthenticated_client, headers)

    text = assert_nothing_said(api_log, FILENAME, "fermentation starts at dawn")
    assert text.count("importer zzz_words_preview failed to preview a .wchat file name of") == 2
    assert "ValueError" in text
    assert db.query(echo_import_service.EchoImport).filter_by(tenant_id=user.id).count() == 0


def test_the_preview_check_sees_a_leak(unauthenticated_client, db, preview_importer, monkeypatch):
    """The mutation: the guard taken out, and the importer's error leaves
    the route whole, quoting the file, which is what uvicorn's own line
    writes. So the check above can fail."""
    monkeypatch.setattr(echo_import_service, "_preview_or_stop", echo_import_service._preview)
    _, headers = _studio(db, "log-words-preview-mutant@example.com")

    with pytest.raises(ValueError, match="fermentation starts at dawn"):
        _upload(unauthenticated_client, "/api/v1/echo/import/preview", headers)


def test_an_import_row_names_the_file_and_the_log_does_not(db, words_importers):
    """Where the words go instead: the import list the owner reads."""
    user, _ = _studio(db, "log-words-row@example.com")
    with pytest.raises(echo_import_service.ImportStopped):
        echo_import_service.run_import(db, user, io.BytesIO(CONTENT), FILENAME, importer="zzz_words_chat")
    record = db.query(echo_import_service.EchoImport).filter_by(tenant_id=user.id).one()
    assert record.filename == FILENAME and json.loads(record.counts_json)["shares"] == 1
