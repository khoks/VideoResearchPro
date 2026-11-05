"""``LOG_FORMAT=json``: one JSON object per line (T-4.11.2.2).

Each line holds ``time``, ``level``, ``logger``, ``message`` and, when a record
has one, ``exception``. Nothing else: a record's ``extra`` fields stay out, so
this format can show nothing the text format does not. Newlines in a message or
a traceback are escaped by JSON, so one record is always one line.

``LOG_FORMAT=text``, the default, changes nothing: ``configure_logging`` returns
at once and the Celery hooks leave Celery's formatters alone.

Three places set up logging, and each is covered:

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
  ``after_setup_task_logger`` signals.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.config import settings

logger = logging.getLogger(__name__)

# The loggers of uvicorn's own config that hold a handler; `uvicorn.error`
# propagates to `uvicorn`.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.access")


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
    value that is neither is a warning and reads as text, never fatal."""
    if not json_logs_enabled():
        if settings.LOG_FORMAT.strip().lower() != "text":
            logger.warning("LOG_FORMAT=%r is neither text nor json; using text", settings.LOG_FORMAT)
        return
    handler = logging.StreamHandler()
    root = logging.getLogger()
    root.handlers[:] = [handler]
    use_json_format(root)
    # A library's DeprecationWarning would otherwise be a bare line on stderr.
    logging.captureWarnings(True)
    for name in _UVICORN_LOGGERS:
        use_json_format(logging.getLogger(name))
