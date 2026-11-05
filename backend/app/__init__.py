"""Runs before anything else in the app, in the API, the worker and Alembic
alike, so a line logged while the rest imports already has its format."""
from app.utils.json_logging import configure_logging

configure_logging()
