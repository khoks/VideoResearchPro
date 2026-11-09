"""Runs before anything else in the app, in the API, the worker and Alembic
alike, so a line logged while the rest imports already has its format and
already keeps credentials out."""
from app.utils.json_logging import configure_logging
from app.utils.log_redaction import install_log_redaction

install_log_redaction()
configure_logging()
