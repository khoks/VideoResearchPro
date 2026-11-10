"""T-4.11.4.9: ``scripts/echo_import.py`` answers a stopped import in one line.

``echo_import_service`` raises ``ImportStopped`` (D-164 point 5) when a
preview or a run fails for a reason that is not the file's. It has logged the
failure by its frames, a run's row already says failed, and
``POST /echo/import`` answers 500 with its words. The script did not catch
it, so the operator's terminal got the whole traceback, whose cause quotes
what the importer could not read: here a Goodreads rating cell holding words.

- In process, each way an import stops (its preview, from ``--preview`` and
  from a run, its own row, a write mid-run): exit 1, nothing on stdout, and
  stderr's last line is the route's words, with none of the file's.
- The real command, ``python scripts/echo_import.py``, on a database of its
  own: the same exit code and line, and no traceback of the stop.

Mutation checks (each failed when this shipped): the script without its
``except ImportStopped``, a copy with the clause cut out, lets the stop
escape ``main`` (``test_the_check_sees_the_stop_escape``), and the real
command run from that copy prints the cell's words
(``test_the_check_sees_the_traceback_on_the_terminal``).
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models.echo_import import EchoImport
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

# What the clause looks like in the script, cut out for the mutation.
_CLAUSE = re.compile(r"\n +except echo_import_service\.ImportStopped as e:\n(?: +#[^\n]*\n)*(?: +[^\n]+\n){2}")


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


def _mutant(tmp_path: Path) -> Path:
    source = SCRIPT.read_text(encoding="utf-8")
    cut = _CLAUSE.sub("\n", source, count=1)
    assert cut != source and "ImportStopped" not in cut, "the mutation cut nothing"
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
def test_a_stopped_import_is_one_line_and_exit_1(cli_db, tmp_path, capsys, case, refuse, words):
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
    assert err.strip().splitlines()[-1] == words, err
    assert_no_words(err)
    rows = cli_db.query(EchoImport).all()
    if case == "mid-run":
        assert [(r.status, r.error) for r in rows] == [("failed", words)], "the row says what the line says"
    else:
        assert rows == [], "nothing was written"


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


def test_the_real_command_prints_one_line(tmp_path):
    done = _terminal(tmp_path, SCRIPT)

    assert done.returncode == 1, done.stderr[-3000:]
    assert done.stdout == ""
    assert done.stderr.strip().splitlines()[-1] == "Preview stopped: ValueError", done.stderr[-3000:]
    assert "ImportStopped" not in done.stderr, "no traceback of the stop"
    assert_no_words(done.stderr)


def test_the_check_sees_the_traceback_on_the_terminal(tmp_path):
    """The mutation on the real command: the cell's words reach the terminal."""
    done = _terminal(tmp_path, _mutant(tmp_path))

    assert done.returncode == 1
    assert "ImportStopped: Preview stopped: ValueError" in done.stderr
    assert RATING in done.stderr
