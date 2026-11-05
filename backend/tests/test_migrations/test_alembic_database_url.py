"""Which database Alembic migrates (T-2.6.7).

alembic.ini repeated `DATABASE_URL` and env.py read only that copy, so after the
database moved, a manual `alembic upgrade head` built an empty file at the old
path and reported success, while the real database stayed behind. The app's
startup was never affected: it names its URL on the Config. These tests run the
real env.py through each way in: the command line, the app's startup, and a
caller that names a throwaway file. That last one is the safety property: a
migration test downgrades to base, so `DATABASE_URL` must never beat it.

`stamp` writes `alembic_version` through the same path as `upgrade` without
replaying the whole chain, so what these show is where a run lands.
"""
from __future__ import annotations

import configparser
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from app.database import Base
from app.services.schema_init_service import ensure_schema_at_head

_BACKEND = Path(__file__).resolve().parents[2]
_INI = _BACKEND / "alembic.ini"


def _config(url: str | None = None, **kwargs) -> Config:
    cfg = Config(str(_INI), **kwargs)
    cfg.set_main_option("script_location", str(_BACKEND / "alembic"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _head() -> str:
    return ScriptDirectory.from_config(_config()).get_current_head()


def _version(url: str) -> str | None:
    engine = create_engine(url)
    try:
        if "alembic_version" not in inspect(engine).get_table_names():
            return None
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()


def _url(path: Path) -> str:
    return "sqlite:///" + path.as_posix()


def _ini_has_a_url() -> bool:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(_INI, encoding="utf-8")
    return parser.has_option("alembic", "sqlalchemy.url")


@pytest.fixture
def app_db(tmp_path, monkeypatch) -> Path:
    """What `settings.DATABASE_URL` points at for the test. Not created here."""
    path = tmp_path / "app.db"
    monkeypatch.setattr(settings, "DATABASE_URL", _url(path))
    return path


def test_alembic_ini_holds_no_copy_of_the_url() -> None:
    """A line there would beat `DATABASE_URL`, the bug itself. Also the guard for
    the command-line test below, which must not reach a live file by way of it."""
    assert not _ini_has_a_url()


def test_with_no_url_named_it_migrates_database_url(app_db) -> None:
    command.stamp(_config(), "head")
    assert _version(_url(app_db)) == _head()


def test_a_named_url_wins_over_database_url(app_db, tmp_path) -> None:
    """Every migration test relies on this one, some of them on the way to base."""
    named = _url(tmp_path / "named.db")
    command.stamp(_config(named), "head")
    assert _version(named) == _head()
    assert not app_db.exists(), "the run touched the app's database"


def test_offline_mode_takes_its_dialect_from_database_url(app_db) -> None:
    """`alembic upgrade --sql` needs a URL for the dialect and connects to nothing."""
    out = io.StringIO()
    command.stamp(_config(output_buffer=out), "head", sql=True)
    assert "INSERT INTO alembic_version" in out.getvalue()
    assert not app_db.exists()


def test_startup_migrates_the_url_it_was_given(app_db, tmp_path) -> None:
    """What the API's lifespan does, and so what restart_services.ps1 relies on:
    the scripts run no Alembic of their own."""
    url = _url(tmp_path / "startup.db")
    result = ensure_schema_at_head(url, Base.metadata, cfg=_config(), upgrade_fn=command.stamp)
    assert result == "fresh_install"
    assert _version(url) == _head()
    assert not app_db.exists()


def test_the_command_line_runs_and_follows_database_url(tmp_path) -> None:
    """`./venv/Scripts/alembic` as the README gives it. `-I` keeps the working
    directory off sys.path, as the console script does: `env.py` imports `app`,
    so without `prepend_sys_path` this is the ModuleNotFoundError every reader of
    the setup steps hit."""
    assert not _ini_has_a_url(), "stamping now could reach the checkout's own database"
    url = _url(tmp_path / "cli.db")
    done = subprocess.run(
        [sys.executable, "-I", "-c", "from alembic.config import main; main(argv=['stamp', 'head'])"],
        cwd=_BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert _version(url) == _head()
