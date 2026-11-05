"""When a source refuses this install, stop offering it (T-1.5.14.1).

A 401 or 403 from a source's search says the service will not answer this
install. It may want credentials the install does not have, or it may be
blocking the address. Either way the next run would get the same answer, so
the submit form stops offering the source until one of three things happens:

- the settings that reach it change, which is how credentials arrive;
- ``HOLD_HOURS`` pass, because a block can lift with nothing changing here
  and nothing else would ever try again. The next run that names the source
  tries it, and a second refusal starts another hold;
- a search answers, which a run sent straight to the API can do.

A refusal about one target of a search is not this: one podcast's feed host,
or one private subreddit, says nothing about the service, and a hold reaches
every tenant. Connectors raise those as ``source_failure.SearchFailed``.

A hold only takes the source off the form. ``POST /jobs`` still accepts it:
that check reads settings, and a hold is one run's evidence, so an API caller
or a saved template loses that source's share and a note on the run, not the
run.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.models.source_refusal import SourceRefusal

logger = logging.getLogger(__name__)

HOLD_HOURS = 24

# The settings that decide how a type is reached. Two of these are secrets:
# only a hash of them is stored, truncated, to notice a change.
_REACHED_THROUGH: dict[str, tuple[str, ...]] = {
    "reddit_post": ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"),
    "mastodon_post": ("MASTODON_INSTANCE_BASE",),
    "bluesky_post": ("BLUESKY_XRPC_BASE",),
    "article": ("BRAVE_SEARCH_API_KEY", "BRAVE_SEARCH_BASE"),
    "tweet": ("TWITTER_BEARER_TOKEN", "TWITTER_API_BASE"),
}


def _fingerprint(source_type: str) -> str:
    values = [str(getattr(settings, name, "")) for name in _REACHED_THROUGH.get(source_type, ())]
    return hashlib.sha256("\0".join(values).encode()).hexdigest()[:16]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record(db: Session, source_type: str, status_code: int) -> None:
    """Start, or restart, the hold on ``source_type``. Never fails a run."""
    try:
        with db.begin_nested():
            db.merge(
                SourceRefusal(
                    source_type=source_type,
                    status_code=status_code,
                    config_fingerprint=_fingerprint(source_type),
                    refused_at=_now(),
                )
            )
    except Exception:
        logger.exception("could not record a refusal by %s", source_type)


def clear(db: Session, source_types: Iterable[str]) -> None:
    """End any hold on sources that just answered. Never fails a run."""
    try:
        with db.begin_nested():
            db.query(SourceRefusal).filter(
                SourceRefusal.source_type.in_(list(source_types))
            ).delete(synchronize_session=False)
    except Exception:
        logger.exception("could not clear source refusals")


def active(db: Session) -> dict[str, dict]:
    """The holds in force, by source type: ``{status, until}``, the end as an
    ISO timestamp. Empty when the table cannot be read: `/health` polls this,
    and a hold is never worth failing it."""
    try:
        rows = db.query(SourceRefusal).all()
    except Exception:
        logger.debug("could not read source refusals", exc_info=True)
        return {}
    now = _now()
    holds: dict[str, dict] = {}
    for row in rows:
        until = row.refused_at + timedelta(hours=HOLD_HOURS)
        if until > now and row.config_fingerprint == _fingerprint(row.source_type):
            holds[row.source_type] = {
                "status": row.status_code,
                "until": until.replace(tzinfo=timezone.utc).isoformat(),
            }
    return holds
