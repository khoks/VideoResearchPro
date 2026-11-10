"""T-4.11.4.7 and T-4.11.4.6's ``run_import`` part, at each changed call site.

The database refuses one statement as SQLite does under another writer's lock
("database is locked"), so SQLAlchemy raises its own ``OperationalError``,
whose text quotes the statement's values: a saved search's question, an
issue's title, the inbox's account address, an import's file name and the
participant its ``self_name`` names. Each test patches the module's logger
and reads every call's arguments.

Each test runs twice. ``mutant`` puts the call site back on the whole
traceback (``traceback_without_text`` patched to render it), and the same run
writes the words: so the check can fail, and the database's error did quote
them. Mutation checks run by hand when this shipped, each failing the named
test:

- ``logger.exception`` back in ``newsletter_service.deliver``
  (``test_a_newsletter_notification_that_fails``);
- a row read there before the rollback, as ``sub.id`` was: the failed flush
  expired it, so the fail-soft handler raised ``PendingRollbackError`` out of
  ``deliver`` (the same test);
- ``logger.exception`` back in ``saved_search_service._notify``
  (``test_a_saved_search_notification_that_fails``);
- ``ss.id`` read there before the rollback, as it was: the run that found a
  change was then recorded as failed (the same test);
- ``logger.exception`` back in ``saved_search_service.execute``
  (``test_a_saved_search_run_that_fails``);
- ``logger.exception`` back in ``scheduler_tasks.scheduler_tick``
  (``test_the_inbox_sync_that_fails``);
- ``run_import``'s first insert and commit back outside any ``try``
  (``test_an_import_whose_first_write_fails`` and both route tests in
  ``tests/test_routers/test_import_first_write.py``);
- the file's name back in that line in place of ``loggable_filename``
  (``test_an_import_whose_first_write_fails``).
"""
from __future__ import annotations

import io
import json
import sqlite3
import traceback
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.models.echo_import import EchoImport
from app.models.notification import Notification
from app.models.saved_search import SavedSearch
from app.services import (
    auth_service,
    echo_import_service,
    email_service,
    newsletter_service,
    saved_search_service,
)
from app.tasks import scheduler_tasks
from tests.test_routers.test_saved_search_alerts import WEEKLY, Agent, _doc, cheap_encode
from tests.test_services.test_book_endnotes import _smoke_run

QUESTION = "What do my Zanzibar quokka sources say about fermentation?"
TITLE = "Zanzibar quokka fermentation digest"
ADDRESS = "zanzibar.quokka@example.com"
PERSON = "Xylophone Wombat"
OTHER = "Quokka Fermentation"
FILENAME = f"WhatsApp Chat with {OTHER}.txt"
CHAT = (
    f"31/01/2024, 21:05 - {PERSON}: hello there\n"
    f"31/01/2024, 21:06 - {OTHER}: hi back\n"
    f"01/02/2024, 07:30 - {PERSON}: see you soon\n"
).encode()
FORBIDDEN = ("zanzibar", "quokka", "fermentation", "xylophone", "wombat")


def said(logger: MagicMock) -> str:
    """Everything the patched logger was given, lower-cased: each line as a
    handler would render it, then every argument and keyword on its own."""
    parts = []
    for call in logger.method_calls:
        args = call.args
        if args:
            try:
                parts.append(str(args[0]) % tuple(args[1:]) if len(args) > 1 else str(args[0]))
            except (TypeError, ValueError):
                pass
        parts.extend(str(a) for a in args)
        parts.extend(f"{k}={v}" for k, v in call.kwargs.items())
    return "\n".join(parts).lower()


def check(logger: MagicMock, mutant: bool) -> str:
    """No word in what was logged, or, for the mutant, the words there."""
    text = said(logger)
    assert text, "nothing was logged, so nothing was checked"
    if mutant:
        assert any(word in text for word in FORBIDDEN), f"the mutant wrote none of the words:\n{text}"
    else:
        for word in FORBIDDEN:
            assert word not in text, f"{word!r} reached a log line:\n{text}"
        assert "operationalerror" in text, "the line still says what failed"
        rendered = [c for c in logger.method_calls if c[0] == "exception" or c.kwargs.get("exc_info")]
        assert not rendered, f"a traceback with its words would be rendered: {rendered}"
    return text


def _whole_traceback(e: BaseException) -> str:
    return "".join(traceback.format_exception(e))


@contextmanager
def mutated(module, mutant: bool):
    """The call site as it was before (``logger.exception``'s traceback)."""
    if not mutant:
        yield
        return
    with patch.object(module, "traceback_without_text", _whole_traceback):
        yield


@contextmanager
def refused(db, start: str, table: str):
    """The database refuses each statement that starts with ``start`` and
    names ``table``, the way SQLite refuses one under another writer's lock."""
    dialect = db.get_bind().dialect
    real_execute, real_many = dialect.do_execute, dialect.do_executemany

    def refuse(statement: str) -> None:
        if statement.lstrip().upper().startswith(start) and f" {table}" in statement:
            raise sqlite3.OperationalError("database is locked")

    def execute(cursor, statement, parameters, context=None):
        refuse(statement)
        return real_execute(cursor, statement, parameters, context)

    def executemany(cursor, statement, parameters, context=None):
        refuse(statement)
        return real_many(cursor, statement, parameters, context)

    with patch.object(dialect, "do_execute", execute), patch.object(dialect, "do_executemany", executemany):
        yield


MUTANT = pytest.mark.parametrize("mutant", [False, True], ids=["fixed", "mutant"])


# ---------------------------------------------------------------------------
# newsletter_service.deliver
# ---------------------------------------------------------------------------


@pytest.fixture
def newsletter_env(tmp_path, monkeypatch):
    import app.services.outputters  # noqa: F401 - registers the newsletter outputter
    import app.tasks.newsletter_tasks  # noqa: F401 - registers the kind

    monkeypatch.setattr(settings, "OUTPUTS_DIR", str(tmp_path / "outputs"))
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://pratidhvani.example")
    with (
        patch("app.services.progress_service.publish_progress"),
        patch("app.services.progress_service.publish_status_change"),
        patch.object(email_service, "send_email", return_value=True),
    ):
        yield


@MUTANT
def test_a_newsletter_notification_that_fails(db, tmp_path, newsletter_env, mutant):
    user = auth_service.create_user(db, email="digest@example.com", password="pw" * 6)
    user.tier = "pro"
    db.commit()
    _smoke_run(db, user.id, tmp_path, topic="Smoking and lungs")
    sub = newsletter_service.save(db, user, cadence={"cadence": "weekly", "weekday": 0, "hour": 8}, title=TITLE)

    with (
        patch.object(newsletter_service, "logger") as log,
        mutated(newsletter_service, mutant),
        refused(db, "INSERT", "notifications"),
    ):
        out = newsletter_service.deliver(db, sub.id, slot=datetime(2026, 10, 19, 8, 0), trigger="manual")

    assert out["status"] == "sent", "a delivered issue is never failed by its bell"
    assert db.query(Notification).filter_by(tenant_id=user.id).count() == 0
    text = check(log, mutant)
    if not mutant:
        assert f"newsletter {sub.id}: notification not stored".lower() in text


# ---------------------------------------------------------------------------
# saved_search_service
# ---------------------------------------------------------------------------


@pytest.fixture
def saved_search_env(monkeypatch):
    monkeypatch.setattr(saved_search_service, "_encode", cheap_encode)
    with patch("app.services.chroma_service.upsert_qa_exchange"), patch.object(
        email_service, "send_email", return_value=True
    ):
        yield


def _saved_search(db, test_user):
    test_user.tier = "pro"
    db.commit()
    _doc(db, test_user.id)
    return saved_search_service.create(db, test_user, question=QUESTION, cadence=WEEKLY)


@MUTANT
def test_a_saved_search_notification_that_fails(db, test_user, saved_search_env, mutant):
    ss = _saved_search(db, test_user)
    saved_search_service.execute(db, ss.id, agent=Agent())  # the baseline
    changed = Agent(answer="A third fermentation round arrived in October.", refs=(("v9", "October statement"),))

    with (
        patch.object(saved_search_service, "logger") as log,
        mutated(saved_search_service, mutant),
        refused(db, "INSERT", "notifications"),
    ):
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=changed)

    assert out["status"] == "ok" and out["changed"] is True, "a run that found a change is never undone by its bell"
    text = check(log, mutant)
    if not mutant:
        assert f"saved search {ss.id}: notification not stored".lower() in text


@MUTANT
def test_a_saved_search_run_that_fails(db, test_user, saved_search_env, mutant):
    ss = _saved_search(db, test_user)

    with (
        patch.object(saved_search_service, "logger") as log,
        mutated(saved_search_service, mutant),
        refused(db, "INSERT", "library_qa_exchanges"),
    ):
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=Agent())

    assert out == {"status": "failed"}
    text = check(log, mutant)
    if not mutant:
        assert f"saved search {ss.id}: run failed".lower() in text
        stored = db.get(SavedSearch, ss.id)
        assert stored.last_status == "failed"
        assert stored.last_error.startswith("OperationalError"), "the words stay on the row the user reads"


# ---------------------------------------------------------------------------
# scheduler_tasks.scheduler_tick
# ---------------------------------------------------------------------------


@MUTANT
def test_the_inbox_sync_that_fails(db, monkeypatch, mutant):
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)
    monkeypatch.setattr(settings, "ECHO_IMAP_ENABLED", True)
    monkeypatch.setattr(settings, "ECHO_IMAP_TENANT_EMAIL", ADDRESS)

    with (
        patch.object(scheduler_tasks, "SessionLocal", return_value=db),
        patch.object(scheduler_tasks.scheduler_service, "run_tick", return_value={"dispatched": 0}) as tick,
        patch.object(scheduler_tasks, "logger") as log,
        mutated(scheduler_tasks, mutant),
        refused(db, "SELECT", "users"),
    ):
        out = scheduler_tasks.scheduler_tick.run()

    assert out == {"dispatched": 0} and tick.called, "the tick goes on"
    text = check(log, mutant)
    if not mutant:
        assert "could not sync the email inbox's row" in text


# ---------------------------------------------------------------------------
# echo_import_service.run_import, its own first write
# ---------------------------------------------------------------------------


def _studio(db, email):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    return user


@MUTANT
def test_an_import_whose_first_write_fails(db, monkeypatch, mutant):
    monkeypatch.setattr(settings, "ECHO_SHARE_PROCESSING", "off")
    user = _studio(db, "import-first-write@example.com")

    with (
        patch.object(echo_import_service, "logger") as log,
        mutated(echo_import_service, mutant),
        refused(db, "INSERT", "echo_imports"),
        pytest.raises(echo_import_service.ImportStopped) as stopped,
    ):
        echo_import_service.run_import(db, user, io.BytesIO(CHAT), FILENAME, options={"self_name": PERSON})

    assert str(stopped.value) == "Import could not start: OperationalError"
    assert db.query(EchoImport).filter_by(tenant_id=user.id).count() == 0, "nothing was written"
    text = check(log, mutant)
    if not mutant:
        assert "a whatsapp import of a .txt file name of" in text
        assert json.dumps(PERSON).lower() not in text
