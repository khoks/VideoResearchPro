"""``LOG_FORMAT=json``: one JSON object per line (T-4.11.2.2).

Each line holds ``time``, ``level``, ``logger``, ``message`` and, when a record
has one, ``exception``. Nothing else: a record's ``extra`` fields stay out, so
this format can show nothing the text format does not. Newlines in a message or
a traceback are escaped by JSON, so one record is always one line.

``LOG_FORMAT=text``, the default, changes nothing: ``configure_logging`` touches
no handler and the Celery hooks leave Celery's formatters alone.

Four places set up logging, and each is covered:

- **The API.** uvicorn configures its own loggers before it imports the app,
  and leaves the root logger bare. ``app/__init__.py`` calls
  ``configure_logging``, which formats uvicorn's handlers and gives the root
  logger one. It runs that early because the imports log: passlib warns about
  the bcrypt build, for one.
- **Alembic.** ``alembic/env.py`` runs ``fileConfig``, which replaces the root
  logger's handlers. It runs in-process when the app migrates at startup, so
  it calls ``configure_logging`` straight after.
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
from datetime import datetime, timezone

from app.config import held_warnings, settings

logger = logging.getLogger(__name__)

# The loggers of uvicorn's own config that hold a handler; `uvicorn.error`
# propagates to `uvicorn`.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.access")

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


def json_logs_enabled() -> bool:
    return settings.LOG_FORMAT.strip().lower() == "json"


def use_json_format(target: logging.Logger) -> None:
    """Give every handler already on ``target`` the JSON formatter."""
    for handler in target.handlers:
        handler.setFormatter(JsonFormatter())


def configure_logging() -> None:
    """The API's logging under ``LOG_FORMAT``: a no-op unless it says json. A
    value that is neither is a warning and reads as text, never fatal. Either
    way it then says what settings held back while they loaded."""
    if json_logs_enabled():
        handler = logging.StreamHandler()
        root = logging.getLogger()
        root.handlers[:] = [handler]
        use_json_format(root)
        # A library's DeprecationWarning would otherwise be a bare line on stderr.
        logging.captureWarnings(True)
        for name in _UVICORN_LOGGERS:
            use_json_format(logging.getLogger(name))
    elif settings.LOG_FORMAT.strip().lower() != "text":
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
