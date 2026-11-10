"""T-4.11.4.6, ``run_import``'s part: an import whose own row cannot be written.

``POST /echo/import`` with a WhatsApp chat named after the person it is with,
and a ``self_name`` naming the other participant. The database refuses the
import's own ``INSERT`` as SQLite does under another writer's lock, so
SQLAlchemy's error quotes the row's values: the file's name and the options.

Before, that insert and its commit sat outside ``run_import``'s ``try``, so
the error left the route whole and uvicorn's "Exception in ASGI application"
line wrote it, values and all. Now the route answers 500 in words, writes no
row, and a root handler at INFO, as ``LOG_FORMAT=json`` or any process that
gives root a handler writes, sees none of the words. The mutation puts the
call site back on the whole traceback and the same request writes them.
"""
from __future__ import annotations

import io
import logging
import traceback

import pytest

from app.config import settings
from app.models.echo_import import EchoImport
from app.services import echo_import_service
from tests.test_routers.test_echo_imports import IMPORT, _post, _studio
from tests.test_services.test_log_tail_call_sites import CHAT, FILENAME, FORBIDDEN, PERSON, refused


@pytest.fixture
def root_log():
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


def _import_cannot_start(client, db, headers):
    with refused(db, "INSERT", "echo_imports"):
        r = _post(client, IMPORT, headers, FILENAME, CHAT, options={"self_name": PERSON})
    assert r.status_code == 500, r.text
    assert r.json() == {"detail": "Import could not start: OperationalError"}


def test_an_import_that_cannot_start_answers_in_words_and_logs_none(unauthenticated_client, db, root_log, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARE_PROCESSING", "off")
    user, headers = _studio(db, "import-cannot-start@example.com")

    _import_cannot_start(unauthenticated_client, db, headers)

    text = root_log.getvalue()
    for word in FORBIDDEN:
        assert word not in text.lower(), f"{word!r} reached the API's log:\n{text}"
    assert "a whatsapp import of a .txt file name of" in text and "OperationalError" in text
    assert db.query(EchoImport).filter_by(tenant_id=user.id).count() == 0, "nothing holds the file's name"


def test_the_check_sees_a_leak(unauthenticated_client, db, root_log, monkeypatch):
    """The mutation: the call site back on the whole traceback, and the same
    request writes the file's name and the participant's, which the database's
    error quoted. So the check above can fail."""
    monkeypatch.setattr(settings, "ECHO_SHARE_PROCESSING", "off")
    monkeypatch.setattr(
        echo_import_service, "traceback_without_text", lambda e: "".join(traceback.format_exception(e))
    )
    _, headers = _studio(db, "import-cannot-start-mutant@example.com")

    _import_cannot_start(unauthenticated_client, db, headers)

    text = root_log.getvalue()
    assert FILENAME in text and PERSON in text
