"""T-4.11.2.2 and T-4.11.3.2: ``LOG_FORMAT``.

The two processes are checked in subprocesses, because what matters is how
logging ends up after uvicorn, Alembic and Celery have each had their turn, and
that cannot be done to the test run's own loggers.

Mutation checks (each failed the named test when this shipped): dropping the
``configure_logging`` call from ``app/__init__.py``
(``test_the_api_writes_json_lines``), or moving it to the end of
``app/main.py``'s imports (the same test: passlib logs while they run);
dropping ``captureWarnings`` (the same test); dropping
the call from ``alembic/env.py``
(``test_json_survives_a_migration_at_startup``); not connecting
``after_setup_logger`` (``test_the_worker_writes_json_lines``); not connecting
``after_setup_task_logger`` (the same test); copying a record's ``job_id`` in
(``test_a_records_extra_fields_stay_out``); ``ensure_ascii=False``
(``test_a_message_in_any_script_stays_ascii_on_the_wire``); dropping the
``route_model_libraries`` call from ``chroma_service`` or ``embedding_service``
(that route's ``test_a_model_load_writes_json_lines``, and
``test_every_model_load_routes_the_libraries_first``); dropping the
``handlers.clear``, the ``propagate``, or ``disable_progress_bar``, or leaving
``huggingface_hub`` off the list (``test_a_model_load_writes_json_lines``);
dropping its text guard (``test_text_leaves_the_model_libraries_alone``). A
worker redirects stderr into the logger, so
``test_a_model_load_in_a_worker_writes_json_lines`` catches only the missing
call and the missing ``propagate``. Not connecting ``celeryd_after_setup``
(``test_the_real_worker_writes_nothing_else``), dropping the ``Beat`` override
(``test_the_real_beat_writes_nothing_else``), and logging the blank-secret
warning from the validator again
(``test_a_blank_secret_warns_in_the_format_of_the_log``). Turning either banner
off whatever the format fails its ``_keeps_its_banner_under_text`` test.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.utils import json_logging
from app.utils.json_logging import JsonFormatter, configure_logging, route_model_libraries

_BACKEND = Path(__file__).resolve().parents[2]
_PYTHON = sys.executable


def _record(msg="hello %s", args=("world",), exc_info=None, **extra) -> logging.LogRecord:
    record = logging.LogRecord("app.thing", logging.WARNING, __file__, 1, msg, args, exc_info)
    record.__dict__.update(extra)
    return record


def test_a_line_holds_the_named_fields():
    entry = json.loads(JsonFormatter().format(_record()))
    assert set(entry) == {"time", "level", "logger", "message"}
    assert entry["level"] == "WARNING"
    assert entry["logger"] == "app.thing"
    assert entry["message"] == "hello world"
    assert datetime.fromisoformat(entry["time"]).utcoffset().total_seconds() == 0


def test_an_exception_is_on_the_same_line():
    try:
        raise ValueError("boom\nsecond line")
    except ValueError:
        line = JsonFormatter().format(_record(exc_info=sys.exc_info()))
    assert "\n" not in line
    entry = json.loads(line)
    assert entry["exception"].startswith("Traceback")
    assert "ValueError: boom" in entry["exception"]


def test_a_newline_in_a_message_cannot_forge_a_second_line():
    line = JsonFormatter().format(_record("a\n%s", ('{"level": "FAKE"}',)))
    assert "\n" not in line
    assert json.loads(line)["level"] == "WARNING"


def test_a_records_extra_fields_stay_out():
    """``extra=`` is how a log call attaches ids. This format adds no field
    the text format would not have shown."""
    entry = json.loads(JsonFormatter().format(_record(job_id="job-1", client_addr="1.2.3.4", user_agent="x")))
    assert set(entry) == {"time", "level", "logger", "message"}


def test_a_message_in_any_script_stays_ascii_on_the_wire():
    line = JsonFormatter().format(_record("अहिंसा %s", ("परमो",)))
    assert line.isascii(), "a cp1252 console must be able to write it"
    assert json.loads(line)["message"] == "अहिंसा परमो"


def test_exc_info_with_nothing_in_it_is_no_exception():
    """``logger.exception`` outside an except block."""
    entry = json.loads(JsonFormatter().format(_record(exc_info=(None, None, None))))
    assert "exception" not in entry


@pytest.fixture
def root_handlers():
    root = logging.getLogger()
    saved = root.handlers[:]
    yield root
    root.handlers[:] = saved


@pytest.mark.parametrize("value", ["text", "TEXT", " text "])
def test_text_touches_nothing(monkeypatch, root_handlers, value):
    monkeypatch.setattr(settings, "LOG_FORMAT", value)
    before = root_handlers.handlers[:]
    uvicorn_log = logging.getLogger("uvicorn")
    probe = logging.NullHandler()
    formatter = logging.Formatter("%(message)s")
    probe.setFormatter(formatter)
    uvicorn_log.addHandler(probe)
    try:
        configure_logging()
        assert root_handlers.handlers == before
        assert probe.formatter is formatter
    finally:
        uvicorn_log.removeHandler(probe)


def test_the_default_is_text():
    assert type(settings).model_fields["LOG_FORMAT"].default == "text"


def test_an_unknown_value_warns_and_reads_as_text(monkeypatch, root_handlers):
    log = MagicMock()
    monkeypatch.setattr(json_logging, "logger", log)
    monkeypatch.setattr(settings, "LOG_FORMAT", "yaml")
    before = root_handlers.handlers[:]
    configure_logging()
    log.warning.assert_called_once()
    assert root_handlers.handlers == before


def test_json_is_read_loosely(monkeypatch, root_handlers):
    monkeypatch.setattr(settings, "LOG_FORMAT", " JSON ")
    configure_logging()
    assert isinstance(root_handlers.handlers[0].formatter, JsonFormatter)


def test_text_leaves_the_model_libraries_alone(monkeypatch):
    monkeypatch.setattr(settings, "LOG_FORMAT", "text")
    library = logging.getLogger("transformers")
    handler = logging.NullHandler()
    library.addHandler(handler)
    monkeypatch.setattr(library, "propagate", False)
    try:
        route_model_libraries()
        assert handler in library.handlers
        assert library.propagate is False
    finally:
        library.removeHandler(handler)


def test_every_model_load_routes_the_libraries_first():
    """Two places build a model, and a third should not be able to forget."""
    sources = {path: path.read_text(encoding="utf-8") for path in (_BACKEND / "app").rglob("*.py")}
    builders = [path for path, text in sources.items() if re.search(r"SentenceTransformer(EmbeddingFunction)?\(", text)]
    assert builders
    for path in builders:
        assert "route_model_libraries()" in sources[path], path


# ---------------------------------------------------------------------------
# The real processes
# ---------------------------------------------------------------------------


def _env(tmp_path: Path, log_format: str | None, **extra: str) -> dict[str, str]:
    """Settings come from the environment, and nothing a process opens is the
    install's: the database and Chroma live in ``tmp_path``, the broker in
    memory."""
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        "CHROMA_PERSIST_DIR": str(tmp_path / "chroma"),
        "CELERY_BROKER_URL": "memory://",
        "CELERY_RESULT_BACKEND": "cache+memory://",
        "PYTHONIOENCODING": "utf-8",
        **extra,
    }
    env.pop("LOG_FORMAT", None)
    if log_format is not None:
        env["LOG_FORMAT"] = log_format
    return env


def _run(script: str, tmp_path: Path, log_format: str | None, **extra: str) -> list[str]:
    """Run ``script`` in a fresh interpreter from backend/, returning its
    non-empty lines of stderr and stdout."""
    env = _env(tmp_path, log_format, **extra)
    done = subprocess.run(
        [_PYTHON, "-c", script], cwd=_BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", timeout=900
    )
    assert done.returncode == 0, done.stderr[-4000:]
    return [line for line in (done.stderr + done.stdout).splitlines() if line.strip()]


def _celery(tmp_path: Path, log_format: str | None, args: list[str], until: str) -> list[str]:
    """The real ``celery`` CLI, until it has written ``until``: what it printed
    by then, all of it, in the order it came. Read before the process is told
    to stop, because on a signal a worker writes one notice straight to the
    stream (NFR-5.1 names it)."""
    output = tmp_path / "celery.log"
    command = [_PYTHON, "-m", "celery", "-A", "app.tasks.celery_app", *args]
    with open(output, "wb") as sink:
        # Unbuffered: a banner printed to a file and then killed would never show.
        env = _env(tmp_path, log_format, PYTHONUNBUFFERED="1")
        process = subprocess.Popen(command, cwd=_BACKEND, env=env, stdout=sink, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 240
            while until not in output.read_text(encoding="utf-8"):
                assert process.poll() is None, output.read_text(encoding="utf-8")[-4000:]
                assert time.monotonic() < deadline, output.read_text(encoding="utf-8")[-4000:]
                time.sleep(0.2)
            written = output.read_text(encoding="utf-8")
        finally:
            process.terminate()
            process.wait(30)
    return [line for line in written.splitlines() if line.strip()]


_API = """
import logging
import warnings

import uvicorn

config = uvicorn.Config("app.main:app", log_level="info")
config.load()

warnings.warn("from a library", FutureWarning)
logging.getLogger("app.probe").info("from the app")
try:
    raise ValueError("boom")
except ValueError:
    logging.getLogger("app.probe").exception("it failed")
logging.getLogger("uvicorn.error").info("from uvicorn")
logging.getLogger("uvicorn.access").info(
    '%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", "/x", "1.1", 200
)
"""

_MIGRATE = """
import logging
import uvicorn

config = uvicorn.Config("app.main:app", log_level="info")
config.load()

from app.config import settings
from app.database import Base
from app.services.schema_init_service import ensure_schema_at_head

print("RESULT", ensure_schema_at_head(settings.DATABASE_URL, Base.metadata), flush=True)
logging.getLogger("app.probe").info("after the migration")
"""

_WORKER = """
import logging
from app.tasks.celery_app import celery_app

celery_app.log.setup(loglevel=logging.INFO, redirect_stdouts=False)

logging.getLogger("app.probe").info("from a task's module")
logging.getLogger("celery.task").info("from the task logger")
logging.getLogger("celery.worker").warning("from the worker")
"""


_MODEL_LOAD = """
import logging
import uvicorn

config = uvicorn.Config("app.main:app", log_level="info")
config.load()

from app.services import chroma_service, embedding_service

{load}

logging.getLogger("transformers.modeling_utils").warning("from transformers")
logging.getLogger("huggingface_hub.file_download").warning("from the hub")
"""

_WORKER_MODEL_LOAD = """
import logging
from app.tasks.celery_app import celery_app

# As a worker runs: at INFO, which draws sentence-transformers' encode bar, with
# stdout and stderr redirected into the logger.
celery_app.log.setup(loglevel=logging.INFO, redirect_stdouts=True)

from app.services import chroma_service

chroma_service.get_qa_collection().upsert(ids=["x"], documents=["hello"])

logging.getLogger("transformers.modeling_utils").warning("from transformers")
logging.getLogger("huggingface_hub.file_download").warning("from the hub")
"""

_NEEDS_THE_MODEL = pytest.mark.skipif(
    os.getenv("OFFLINE"),
    reason="needs multilingual sentence-transformer weights to be downloadable",
)


def _json_lines(lines: list[str]) -> list[dict]:
    return [json.loads(line) for line in lines]


def test_the_api_writes_json_lines(tmp_path):
    entries = _json_lines(_run(_API, tmp_path, "json"))
    by_logger = {(e["logger"], e["message"]) for e in entries}
    assert ("app.probe", "from the app") in by_logger
    assert ("uvicorn.error", "from uvicorn") in by_logger
    assert ("uvicorn.access", '127.0.0.1:1 - "GET /x HTTP/1.1" 200') in by_logger
    failed = next(e for e in entries if e["message"] == "it failed")
    assert failed["level"] == "ERROR" and "ValueError: boom" in failed["exception"]
    warned = [e["message"] for e in entries if e["logger"] == "py.warnings"]
    assert any("from a library" in message for message in warned), "other libraries warn on import too"


@_NEEDS_THE_MODEL
@pytest.mark.parametrize(
    "load",
    [
        pytest.param('embedding_service.encode(["hello"])', id="embedding_service"),
        pytest.param('chroma_service.get_qa_collection().upsert(ids=["x"], documents=["hello"])', id="chroma_service"),
    ],
)
def test_a_model_load_writes_json_lines(tmp_path, load):
    """The real load, by each of its two routes. ``transformers`` and
    ``huggingface_hub`` hold stderr handlers of their own, and the weight bar
    goes straight to stderr, so ``_json_lines`` fails on anything left bare.
    The hub also propagates, so a line kept twice would count two."""
    entries = _json_lines(_run(_MODEL_LOAD.format(load=load), tmp_path, "json"))
    lines = [(e["logger"], e["message"]) for e in entries]
    assert lines.count(("transformers.modeling_utils", "from transformers")) == 1
    assert lines.count(("huggingface_hub.file_download", "from the hub")) == 1


@_NEEDS_THE_MODEL
def test_a_model_load_in_a_worker_writes_json_lines(tmp_path):
    entries = _json_lines(_run(_WORKER_MODEL_LOAD, tmp_path, "json"))
    lines = [(e["logger"], e["message"]) for e in entries]
    assert lines.count(("transformers.modeling_utils", "from transformers")) == 1
    assert lines.count(("huggingface_hub.file_download", "from the hub")) == 1


def test_text_leaves_the_api_as_it_was(tmp_path):
    lines = _run(_API, tmp_path, None)
    assert '{"time"' not in "\n".join(lines)
    assert any("from uvicorn" in line for line in lines), "uvicorn's own format is still there"


def test_json_survives_a_migration_at_startup(tmp_path):
    """Alembic's fileConfig replaces the root logger's handlers."""
    lines = _run(_MIGRATE, tmp_path, "json")
    assert "RESULT fresh_install" in lines
    entries = _json_lines([line for line in lines if not line.startswith("RESULT")])
    assert any(e["message"] == "after the migration" for e in entries)
    assert any(e["logger"].startswith("alembic") for e in entries), "the migration's own lines are JSON too"


def test_the_worker_writes_json_lines(tmp_path):
    entries = _json_lines(_run(_WORKER, tmp_path, "json"))
    assert {e["message"] for e in entries} >= {
        "from a task's module",
        "from the task logger",
        "from the worker",
    }


def test_text_leaves_the_worker_as_it_was(tmp_path):
    lines = _run(_WORKER, tmp_path, "text")
    assert any("from the worker" in line for line in lines)
    assert not any(line.startswith("{") for line in lines)


_REAL_WORKER = ["worker", "--pool=solo", "--loglevel=info"]
# The worker prints its banner and then connects, so stopping there has seen it
# or its absence, and spares the embedding model that loads once it is ready.
_WORKER_CONNECTED = "Connected to memory://"
_BEAT_STARTED = "beat: Starting"


def _real_beat(tmp_path: Path) -> list[str]:
    return ["beat", "--loglevel=info", "-s", str(tmp_path / "beat-schedule")]


def test_the_real_worker_writes_nothing_else(tmp_path):
    """T-4.11.3.2: a start banner is ``print``, which no handler sees."""
    entries = _json_lines(_celery(tmp_path, "json", _REAL_WORKER, _WORKER_CONNECTED))
    assert any(e["message"].startswith(_WORKER_CONNECTED) for e in entries)


def test_the_real_worker_keeps_its_banner_under_text(tmp_path):
    lines = _celery(tmp_path, "text", _REAL_WORKER, _WORKER_CONNECTED)
    assert any(".> transport:" in line for line in lines)


def test_the_real_beat_writes_nothing_else(tmp_path):
    entries = _json_lines(_celery(tmp_path, "json", _real_beat(tmp_path), _BEAT_STARTED))
    assert any(e["message"].startswith(_BEAT_STARTED) for e in entries)


def test_the_real_beat_keeps_its_banner_under_text(tmp_path):
    lines = _celery(tmp_path, "text", _real_beat(tmp_path), _BEAT_STARTED)
    assert any("LocalTime ->" in line for line in lines)


@pytest.mark.parametrize("log_format", ["json", None])
def test_a_blank_secret_warns_in_the_format_of_the_log(tmp_path, log_format):
    """T-4.11.3.2: settings load before logging can have a format, ``LOG_FORMAT``
    being one of them, so the warning waits for it. ``_json_lines`` fails on a
    bare line, and exactly one says it however often logging is set up."""
    lines = _run(_API, tmp_path, log_format, JWT_SECRET="")
    assert sum("JWT_SECRET is blank" in line for line in lines) == 1
    if log_format == "json":
        [warned] = [e for e in _json_lines(lines) if "JWT_SECRET is blank" in e["message"]]
        assert warned["level"] == "WARNING" and warned["logger"] == "app.config"
