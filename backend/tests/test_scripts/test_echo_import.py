"""T-4.11.4.9: ``scripts/echo_import.py`` answers a stopped import in one line.

``echo_import_service`` raises ``ImportStopped`` (D-164 point 5) when a
preview or a run fails for a reason that is not the file's. It has logged the
failure by its frames, a run's row already says failed, and
``POST /echo/import`` answers 500 with its words. The script did not catch
it, so the operator's terminal got the whole traceback, whose cause quotes
what the importer could not read: here a Goodreads rating cell holding words.

- In process, each way an import stops (its preview, from ``--preview`` and
  from a run, its own row, a write mid-run): exit 1, nothing on stdout, and
  stderr is the route's words, with none of the file's.
- A run that stopped after a committed batch keeps it under a failed import,
  so a second line names that import and what it holds, counted from the
  rows (its ``counts_json`` counts the batch that rolled back too). The same
  for an ``ExportUnreadable`` raised mid-run, whose first line then says
  "stopped", not "Not imported".
- The service's own line of the stop, its frames, stays out of the
  terminal: the script filters it from the service's logger for the run
  alone, and the API keeps it.
- The real command, ``python scripts/echo_import.py``, on a database of its
  own: the same exit code, and stderr is that one line and nothing else
  beyond passlib's note about the bcrypt build, which every import of the
  app writes.

Mutation checks (each failed): the script without its
``except ImportStopped``, a copy with the clause cut out, lets the stop
escape ``main`` (``test_the_check_sees_the_stop_escape``), and the real
command run from that copy prints the cell's words
(``test_the_check_sees_the_traceback_on_the_terminal``). The script without
its log filter prints the service's frames above the line
(``test_the_check_sees_the_frames_on_the_terminal``, and the in-process
log check). The service raising without the import's id leaves the second
line out (the two part-way tests).
"""
from __future__ import annotations

import importlib.util
import io
import json
import logging
import re
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.connectors.archive import ExportUnreadable
from app.database import Base
from app.models.echo_import import EchoImport
from app.models.share import Share
from app.services import echo_import_service
from tests.test_routers.test_echo_imports import _studio
from tests.test_services.test_log_tail_call_sites import CHAT, FILENAME, PERSON, refused
from tests.test_utils.test_log_redaction import _BACKEND, _PYTHON, _env

SCRIPT = _BACKEND / "scripts" / "echo_import.py"
EMAIL = "cli-import-stopped@example.com"

# A Goodreads export whose rating cell holds words: the importer's int()
# raises a ValueError quoting them, and the preview stops.
RATING = "Zanzibar quokka"
GOODREADS_NAME = "goodreads_library_export.csv"
GOODREADS = (
    "Book Id,Title,Author,My Rating,Date Read,Date Added,Bookshelves,Exclusive Shelf\n"
    f"101,The Choice,Russ Roberts,{RATING},2024/01/20,2023/12/01,economics,read\n"
).encode()
FORBIDDEN = ("zanzibar", "quokka", "fermentation", "xylophone", "wombat")

# What the clause looks like in the script, cut out for the mutation: the
# `except` line to its `return 1`.
_CLAUSE = re.compile(r"\n +except echo_import_service\.ImportStopped as e:\n(?:[^\n]*\n)*? +return 1\n")
# The log filter, cut out for the other mutation.
_FILTER = re.compile(r"\n +service_log\.addFilter\(_not_a_stop\)\n")

# What every import of the app writes on stderr under bcrypt 4.x, whatever the
# script then does (requirements.txt says why bcrypt stays there).
_PASSLIB_NOTE = re.compile(
    r"\(trapped\) error reading bcrypt version\nTraceback \(most recent call last\):\n"
    r"(?:[ \t][^\n]*\n)*AttributeError: module 'bcrypt' has no attribute '__about__'\n"
)


def _kept(import_id: str, shares: int, events: int = 0, facts: int = 0) -> str:
    return (
        f"Import {import_id} is marked failed and keeps what it stored before it stopped "
        f"(shares: {shares}, activity events: {events}, facts: {facts}). "
        "Undo it under Your imports on the Echo import page before running this file again."
    )


def _load(path: Path = SCRIPT):
    spec = importlib.util.spec_from_file_location(f"echo_import_cli_{path.parent.name}", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


class _Shared:
    """The test session, which the script must not close."""

    def __init__(self, db):
        self._db = db

    def __call__(self):
        return self

    def __getattr__(self, attr):
        return getattr(self._db, attr)

    def close(self):
        pass


def _mutant(tmp_path: Path, pattern: re.Pattern[str] = _CLAUSE, gone: str = "ImportStopped") -> Path:
    source = SCRIPT.read_text(encoding="utf-8")
    cut = pattern.sub("\n", source, count=1)
    assert cut != source and gone not in cut, "the mutation cut nothing"
    path = tmp_path / "mutant" / "echo_import.py"
    path.parent.mkdir()
    path.write_text(cut, encoding="utf-8")
    return path


def assert_no_words(text: str) -> None:
    for word in FORBIDDEN:
        assert word not in text.lower(), f"{word!r} reached the terminal:\n{text}"


@pytest.fixture
def cli_db(db, monkeypatch):
    # The script sets this itself; monkeypatch puts the suite's value back.
    monkeypatch.setattr(settings, "ECHO_SHARE_PROCESSING", "off")
    _studio(db, EMAIL)
    return db


def _run(cli, db, tmp_path, name: str, data: bytes, *flags: str) -> int:
    path = tmp_path / name
    path.write_bytes(data)
    return cli.main(["--email", EMAIL, "--file", str(path), *flags], session_factory=_Shared(db))


def _whatsapp_flags() -> tuple[str, ...]:
    return ("--options", json.dumps({"self_name": PERSON}))


@pytest.mark.parametrize(
    "case, refuse, words",
    [
        ("preview", None, "Preview stopped: ValueError"),
        ("run-preview", None, "Preview stopped: ValueError"),
        ("row", "echo_imports", "Import could not start: OperationalError"),
        ("mid-run", "shares", "Import stopped: OperationalError"),
    ],
)
def test_a_stopped_import_is_the_routes_words_and_exit_1(cli_db, tmp_path, capsys, case, refuse, words):
    cli = _load()
    if refuse is None:
        flags = ("--preview",) if case == "preview" else ()
        code = _run(cli, cli_db, tmp_path, GOODREADS_NAME, GOODREADS, *flags)
    else:
        with refused(cli_db, "INSERT", refuse):
            code = _run(cli, cli_db, tmp_path, FILENAME, CHAT, *_whatsapp_flags())
    out, err = capsys.readouterr()

    assert code == 1
    assert out == ""
    assert_no_words(err)
    rows = cli_db.query(EchoImport).all()
    if case == "mid-run":
        assert [(r.status, r.error) for r in rows] == [("failed", words)], "the row says what the line says"
        # Its one batch rolled back, so the row holds nothing, and says so.
        assert err.splitlines() == [words, _kept(rows[0].id, shares=0)], err
    else:
        assert rows == [], "nothing was written"
        assert err.splitlines() == [words], err


@contextmanager
def _refused_after(db, table: str, allowed: int):
    """The database takes the first ``allowed`` inserts into ``table``, then
    refuses each one after, the way SQLite refuses one under another
    writer's lock."""
    dialect = db.get_bind().dialect
    real_execute, real_many = dialect.do_execute, dialect.do_executemany
    seen = []

    def refuse(statement: str) -> None:
        if statement.lstrip().upper().startswith("INSERT") and f" {table}" in statement:
            seen.append(statement)
            if len(seen) > allowed:
                raise sqlite3.OperationalError("database is locked")

    def execute(cursor, statement, parameters, context=None):
        refuse(statement)
        return real_execute(cursor, statement, parameters, context)

    def executemany(cursor, statement, parameters, context=None):
        refuse(statement)
        return real_many(cursor, statement, parameters, context)

    with patch.object(dialect, "do_execute", execute), patch.object(dialect, "do_executemany", executemany):
        yield


def test_a_run_that_stopped_part_way_names_its_import(cli_db, tmp_path, capsys, monkeypatch):
    """The chat's first share is committed in a batch of its own, the second
    batch is refused: the share stays under the failed import, and the second
    line says which import and that it holds one share. Its ``counts_json``
    counted the refused share too, so the line counts the rows."""
    monkeypatch.setattr(echo_import_service, "_BATCH", 1)
    cli = _load()
    with _refused_after(cli_db, "shares", allowed=1):
        code = _run(cli, cli_db, tmp_path, FILENAME, CHAT, *_whatsapp_flags())
    out, err = capsys.readouterr()

    (row,) = cli_db.query(EchoImport).all()
    assert (row.status, row.error) == ("failed", "Import stopped: OperationalError")
    assert cli_db.query(Share).filter(Share.import_id == row.id).count() == 1, "the first batch stayed"
    assert json.loads(row.counts_json)["shares"] == 2, "the row's own count says more than it holds"
    assert code == 1
    assert out == ""
    assert err.splitlines() == ["Import stopped: OperationalError", _kept(row.id, shares=1)], err
    assert_no_words(err)


def test_an_unreadable_file_found_part_way_names_its_import(cli_db, tmp_path, capsys, monkeypatch):
    """``ExportUnreadable`` raised after a batch was committed (Apple Health's
    "export.xml is damaged" can come gigabytes in): the first line says the
    run stopped, in the route's words, and the second names the import."""
    damaged = "export.xml is damaged: no element found: line 9, column 0"
    real_parse = echo_import_service._parse

    def parse_then_break(importer, source, options, stats, tenant_id):
        yield next(iter(real_parse(importer, source, options, stats, tenant_id=tenant_id)))
        raise ExportUnreadable(damaged)

    monkeypatch.setattr(echo_import_service, "_BATCH", 1)
    monkeypatch.setattr(echo_import_service, "_parse", parse_then_break)
    code = _run(_load(), cli_db, tmp_path, FILENAME, CHAT, *_whatsapp_flags())
    out, err = capsys.readouterr()

    (row,) = cli_db.query(EchoImport).all()
    assert (row.status, row.error) == ("failed", damaged)
    assert code == 1
    assert out == ""
    assert err.splitlines() == [f"Import stopped: {damaged}", _kept(row.id, shares=1)], err


def test_an_unreadable_file_before_the_run_is_not_imported(cli_db, tmp_path, capsys):
    """Before any row: "Not imported", one line, as before."""
    code = _run(_load(), cli_db, tmp_path, "notes.txt", b"nothing an importer reads\n")
    out, err = capsys.readouterr()

    assert code == 1
    assert out == ""
    (line,) = err.splitlines()
    assert line.startswith("Not imported: "), err
    assert cli_db.query(EchoImport).all() == []


def test_stored_by_counts_what_an_import_holds(cli_db):
    """What the second line reads: the import's shares, its events and its
    facts, found as the undo finds them, and nobody else's."""
    from app.models.activity_event import ActivityEvent
    from app.models.personal_context import PersonalContext
    from app.models.user import User

    user = cli_db.query(User).filter(User.email == EMAIL).one()
    other = _studio(cli_db, "someone-else@example.com")[0]
    record = echo_import_service.run_import(
        cli_db, user, io.BytesIO(CHAT), FILENAME, options={"self_name": PERSON},
    )
    other_record = echo_import_service.run_import(
        cli_db, other, io.BytesIO(CHAT), FILENAME, options={"self_name": PERSON},
    )
    for owner, imported in ((user, record), (other, other_record)):
        cli_db.add(ActivityEvent(
            tenant_id=owner.id, user_id=owner.id, connector="whatsapp", external_id=f"e-{imported.id}",
            event_type="message", occurred_at=imported.created_at,
            payload_json=json.dumps({"_import": imported.id}),
        ))
        cli_db.add(PersonalContext(
            tenant_id=owner.id, user_id=owner.id, kind="interest", key=f"k-{imported.id}",
            value="v", source=f"import:{imported.id}",
        ))
    cli_db.commit()

    held = echo_import_service.stored_by(cli_db, user.id, record.id)
    assert held == {"shares": json.loads(record.counts_json)["shares"], "events": 1, "facts": 1}
    with pytest.raises(echo_import_service.ImportNotFound):
        echo_import_service.stored_by(cli_db, user.id, other_record.id)


def _stop_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if echo_import_service.is_stop_log(r)]


def test_the_services_line_of_the_stop_stays_off_the_terminal(cli_db, tmp_path, capsys, caplog):
    """The service logs a stop by its frames: the route's caller keeps that
    line, the script drops it for its run alone, and puts the logger back."""
    caplog.set_level(logging.INFO, logger=echo_import_service.__name__)
    with pytest.raises(echo_import_service.ImportStopped):
        echo_import_service.preview(io.BytesIO(GOODREADS), GOODREADS_NAME)
    assert len(_stop_records(caplog)) == 1, "the API's log keeps the frames"
    caplog.clear()

    code = _run(_load(), cli_db, tmp_path, GOODREADS_NAME, GOODREADS, "--preview")
    capsys.readouterr()
    assert code == 1
    assert _stop_records(caplog) == [], "the script left the service's line of the stop in"
    assert logging.getLogger(echo_import_service.__name__).filters == [], "the filter outlived the run"

    with pytest.raises(echo_import_service.ImportStopped):
        echo_import_service.preview(io.BytesIO(GOODREADS), GOODREADS_NAME)
    assert len(_stop_records(caplog)) == 1


def test_the_check_sees_the_services_line(cli_db, tmp_path, caplog, monkeypatch):
    """The mutation: the script without its filter lets the line through."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    caplog.set_level(logging.INFO, logger=echo_import_service.__name__)
    cli = _load(_mutant(tmp_path, _FILTER, "addFilter"))
    assert _run(cli, cli_db, tmp_path, GOODREADS_NAME, GOODREADS, "--preview") == 1
    assert len(_stop_records(caplog)) == 1


def test_the_check_sees_the_stop_escape(cli_db, tmp_path, monkeypatch):
    """The mutation: the script without its clause, and the same run leaves
    ``main`` with the stop, which Python prints whole, cause and all."""
    monkeypatch.setattr(sys, "path", list(sys.path))  # the copy puts its own folder first
    cli = _load(_mutant(tmp_path))
    with pytest.raises(echo_import_service.ImportStopped) as stopped:
        _run(cli, cli_db, tmp_path, GOODREADS_NAME, GOODREADS, "--preview")
    assert RATING in str(stopped.value.__cause__), "the cause quotes the cell"


def _terminal(tmp_path: Path, script: Path) -> subprocess.CompletedProcess:
    """The command as an operator runs it, on a database of its own holding a
    Studio account. A preview, so nothing could be written or embedded, and
    ``_env`` blanks every provider key."""
    url = f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as session:
            _studio(session, EMAIL)
    finally:
        engine.dispose()
    export = tmp_path / GOODREADS_NAME
    export.write_bytes(GOODREADS)
    env = _env(tmp_path, PYTHONPATH=str(_BACKEND))
    return subprocess.run(
        [_PYTHON, str(script), "--email", EMAIL, "--file", str(export), "--preview"],
        cwd=_BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", timeout=240,
    )


def _beside_passlib(stderr: str) -> list[str]:
    return _PASSLIB_NOTE.sub("", stderr, count=1).splitlines()


def test_the_real_command_prints_one_line(tmp_path):
    done = _terminal(tmp_path, SCRIPT)

    assert done.returncode == 1, done.stderr[-3000:]
    assert done.stdout == ""
    assert _beside_passlib(done.stderr) == ["Preview stopped: ValueError"], done.stderr[-3000:]
    assert_no_words(done.stderr)


def test_the_check_sees_the_traceback_on_the_terminal(tmp_path):
    """The mutation on the real command: the cell's words reach the terminal."""
    done = _terminal(tmp_path, _mutant(tmp_path))

    assert done.returncode == 1
    assert "ImportStopped: Preview stopped: ValueError" in done.stderr
    assert RATING in done.stderr


def test_the_check_sees_the_frames_on_the_terminal(tmp_path):
    """The mutation on the real command: without the filter, the service's
    frames come out above the line, a traceback of many lines."""
    done = _terminal(tmp_path, _mutant(tmp_path, _FILTER, "addFilter"))

    assert done.returncode == 1
    lines = _beside_passlib(done.stderr)
    assert lines[-1] == "Preview stopped: ValueError"
    assert len(lines) > 1 and "app.services.echo_import_service" in lines[0], done.stderr[-3000:]
