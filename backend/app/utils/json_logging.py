"""``LOG_FORMAT=json``: one JSON object per line (T-4.11.2.2).

Each line holds ``time``, ``level``, ``logger``, ``message`` and, when a record
has one, ``exception``. Nothing else: a record's ``extra`` fields stay out, so
this format can show nothing the text format does not. Newlines in a message or
a traceback are escaped by JSON, so one record is always one line.

``LOG_FORMAT=text``, the default, leaves uvicorn's, Celery's and the root
logger's handlers as they are, and gives the ``app`` logger one of its own
(``AppStderrHandler``). uvicorn's logging config names only its own three
loggers, so in the API nothing else would write an ``app.*`` line: an INFO
line was dropped and a WARNING went out bare through ``logging.lastResort``,
with no time, level or logger name. That handler writes only while the root
logger has none, so wherever something has given root one (Celery, Alembic's
``fileConfig``, ``LOG_FORMAT=json``, pytest) a line is still written once.

Four places set up logging, and each is covered:

- **The API.** uvicorn configures its own loggers before it imports the app,
  and leaves the root logger bare. ``app/__init__.py`` calls
  ``configure_logging``, which under json formats uvicorn's handlers and gives
  the root logger one, and under text gives the ``app`` logger its handler. It
  runs that early because the imports log: passlib warns about the bcrypt
  build, for one.
- **Alembic.** ``alembic/env.py`` runs ``fileConfig``, which replaces the root
  logger's handlers. It runs in-process when the app migrates at startup, so
  it calls ``configure_logging`` straight after, and ``schema_init_service``
  puts the root logger back as it found it once the migration is done.
- **Celery.** The worker and beat replace the root logger's handlers when they
  start, after the app has imported, so ``app/tasks/celery_app.py`` calls
  ``use_json_format`` from Celery's ``after_setup_logger`` and
  ``after_setup_task_logger`` signals. Their start banners are printed, not
  logged, so under json that file turns them off.
- **The model libraries.** ``transformers`` and ``huggingface_hub`` give their
  own loggers a stderr handler when they import, which is long after all of
  the above. So every place that builds a model calls
  ``route_model_libraries`` first.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app.config import held_warnings, settings

logger = logging.getLogger(__name__)

# The loggers of uvicorn's own config that hold a handler; `uvicorn.error`
# propagates to `uvicorn`.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.access")

# Every module of the app logs as `logging.getLogger(__name__)`, under this.
_APP_LOGGER = "app"
# What tells the app's handler from any other, a copy from a reloaded module
# included, so it is never added twice.
_APP_HANDLER_NAME = "pratidhvani.app_stderr"
_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Each holds a stderr handler of its own once imported, so its lines write
# around the root logger. `transformers` also stops propagating.
_MODEL_LIBRARY_LOGGERS = ("transformers", "huggingface_hub")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            entry["exception"] = record.exc_text
        # ASCII on purpose: a Windows console or log file can be cp1252, where
        # a Devanagari message would fail to write. The escapes decode exactly.
        return json.dumps(entry)


class AppStderrHandler(logging.StreamHandler):
    """The app's own lines under ``LOG_FORMAT=text``: on stderr, as uvicorn
    writes its own, INFO and up, with the time, the level and the logger name.

    It stands in for a root handler, so it writes only while the root logger
    has none. In the API, where uvicorn leaves root bare, it is the one handler
    an ``app.*`` record meets. Where something else has given root a handler,
    the Celery worker and beat, Alembic's ``fileConfig`` when the app migrates
    at startup, ``LOG_FORMAT=json``, pytest, the record is written there, in
    that format, and this steps aside. Asked when each record comes, not when
    the handler is added, because Celery sets the root logger up after the app
    has imported.

    On the ``app`` logger, never root, and root's level stays: a library that
    logs at INFO keeps going unseen. httpx writes a whole URL there
    (T-3.7.2.9).

    Like ``logging.lastResort``, which it replaces for these records, it writes
    to whatever ``sys.stderr`` is when a record comes.
    """

    def __init__(self) -> None:
        logging.Handler.__init__(self, logging.INFO)
        self.set_name(_APP_HANDLER_NAME)
        self.setFormatter(logging.Formatter(_TEXT_FORMAT))

    @property
    def stream(self):  # type: ignore[override]
        return sys.stderr

    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        if logging.getLogger().handlers:
            return False
        return super().filter(record)


def json_logs_enabled() -> bool:
    return settings.LOG_FORMAT.strip().lower() == "json"


def use_json_format(target: logging.Logger) -> None:
    """Give every handler already on ``target`` the JSON formatter."""
    for handler in target.handlers:
        handler.setFormatter(JsonFormatter())


def give_the_app_a_handler() -> None:
    """Add ``AppStderrHandler`` to the ``app`` logger, once however often it is
    called."""
    app_logger = logging.getLogger(_APP_LOGGER)
    if not any(handler.get_name() == _APP_HANDLER_NAME for handler in app_logger.handlers):
        app_logger.addHandler(AppStderrHandler())


def configure_logging() -> None:
    """The API's logging under ``LOG_FORMAT``. Under json, the root logger's
    handler and uvicorn's take the JSON format. Under text, the ``app`` logger
    gets ``AppStderrHandler`` and nothing else changes. A value that is neither
    is a warning and reads as text, never fatal. Either way it then says what
    settings held back while they loaded. Safe to call more than once."""
    if json_logs_enabled():
        handler = logging.StreamHandler()
        root = logging.getLogger()
        root.handlers[:] = [handler]
        use_json_format(root)
        # A library's DeprecationWarning would otherwise be a bare line on stderr.
        logging.captureWarnings(True)
        for name in _UVICORN_LOGGERS:
            use_json_format(logging.getLogger(name))
    else:
        give_the_app_a_handler()
        if settings.LOG_FORMAT.strip().lower() != "text":
            logger.warning("LOG_FORMAT=%r is neither text nor json; using text", settings.LOG_FORMAT)
    while held_warnings:
        logging.getLogger("app.config").warning(held_warnings.pop(0))


def route_model_libraries() -> None:
    """Under json, send the model libraries' lines through the root logger and
    turn off their progress bars. A no-op under text.

    Call it before building a model, so the load's own lines are covered: the
    weight bar, and a load report of several lines, which comes out as one
    record. ``configure_logging`` cannot do this: these libraries set their
    loggers up as they import, and importing them there would add seconds to
    every process that never loads a model.
    """
    if not json_logs_enabled():
        return
    # Imports huggingface_hub too. Its import is what installs the handlers.
    from transformers.utils import logging as transformers_logging

    for name in _MODEL_LIBRARY_LOGGERS:
        library = logging.getLogger(name)
        library.handlers.clear()
        library.propagate = True
    # The hub's download bars go with it.
    transformers_logging.disable_progress_bar()
