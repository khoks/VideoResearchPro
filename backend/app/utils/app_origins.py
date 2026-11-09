"""The addresses the app is opened at, as one list (T-4.11.3.3).

Two checks read it, and nothing else decides either of them:

* CORS (``middleware/cors.py``): which pages a browser lets call the API.
* OAuth start (``oauth_service.start_flow``): which addresses Google or GitHub
  sign-in may return to.

The list is the origin of ``APP_BASE_URL`` plus each entry of
``OAUTH_ALLOWED_REDIRECT_ORIGINS``, compared by scheme, host and port. The
second setting kept its name when CORS began reading it, because a rename
breaks every ``.env`` that pins it, so it now covers more than its name says.
Before, CORS was hard-coded to ``localhost:5173`` and ``localhost:3000``: an
install at any other address needed a code edit, and a page at ``:3000``
passed CORS and was then refused at OAuth start. Nothing in the repository
served the app at ``:3000``, so it is not a default any more.

No wildcard. The API allows credentials, and Starlette answers a ``*`` that
comes with credentials by echoing back whatever origin asked: every site on the
web would pass. A bad entry is logged once and skipped, never fatal, and
skipping one only ever allows less.

Both checks read the settings when they run, the parse cached by value, so
they cannot disagree, and a test that changes a setting changes both.
"""
from __future__ import annotations

import functools
import logging
import urllib.parse

from app.config import settings

logger = logging.getLogger(__name__)

Origin = tuple[str, str, int]

_DEFAULT_PORTS = {"http": 80, "https": 443}


def origin_of(url: str) -> Origin | None:
    """``(scheme, host, port)`` of ``url``, or None when it is not a plain
    http(s) URL. Refused rather than parsed: anything a browser could read
    differently from ``urlsplit``. Credentials before the host, a backslash,
    and spaces or control characters (which ``urlsplit`` drops silently) can
    each put one host in this answer and another in the address bar."""
    if "\\" in url or any(ch <= " " for ch in url):
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    default_port = _DEFAULT_PORTS.get(parts.scheme)
    if default_port is None or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    return parts.scheme, parts.hostname, default_port if port is None else port


def allowed() -> frozenset[Origin]:
    """The origin of ``APP_BASE_URL`` plus ``OAUTH_ALLOWED_REDIRECT_ORIGINS``."""
    return _parse(settings.APP_BASE_URL, settings.OAUTH_ALLOWED_REDIRECT_ORIGINS)


def allows(url: str) -> bool:
    """Whether ``url`` is on one of the allowed origins: a browser's ``Origin``
    header for CORS, a ``redirect_uri`` for OAuth start."""
    origin = origin_of(url)
    return origin is not None and origin in allowed()


def describe() -> str:
    """The list as a browser writes origins, for the startup log."""
    return ", ".join(sorted(_serialise(o) for o in allowed())) or "(none)"


@functools.lru_cache(maxsize=8)
def _parse(app_base_url: str, extra: str) -> frozenset[Origin]:
    """Cached by the two values, so each bad entry is logged once per process,
    not on every request that carries an ``Origin``."""
    found: set[Origin] = set()
    for entry in [app_base_url, *extra.split(",")]:
        entry = entry.strip()
        if not entry:
            continue
        if "*" in entry:
            logger.warning(
                "App origins: ignoring %r. A wildcard is refused: the API allows credentials, "
                "so CORS would let every site's pages call it. Name each origin.",
                entry,
            )
            continue
        origin = origin_of(entry)
        if origin is None:
            logger.warning("App origins: ignoring %r, which is not an http(s) origin", entry)
            continue
        found.add(origin)
    return frozenset(found)


def _serialise(origin: Origin) -> str:
    scheme, host, port = origin
    if ":" in host:
        host = f"[{host}]"
    return f"{scheme}://{host}" if port == _DEFAULT_PORTS[scheme] else f"{scheme}://{host}:{port}"
