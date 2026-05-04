"""Hybrid article extractor: trafilatura primary, Playwright fallback.

See module-level docstring at :mod:`app.services.article_extraction`
for the design rationale.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
import trafilatura

from app.config import settings

logger = logging.getLogger(__name__)

# Words below this threshold are treated as a likely failure mode
# (navigation page, paywall stub, error page, near-empty SPA shell).
# Trafilatura readily extracts these but the result is rarely useful
# for retrieval. The threshold matches the human reading sense of
# "this is shorter than an article" — a real news piece or blog
# post is almost always 200+ words. Below MIN_WORD_COUNT we try the
# Playwright fallback (today: stub) and, if that also fails, return
# the partial extract as best-effort *unless* it's so short
# (`HARD_FLOOR_WORDS`) that it's clearly junk — e.g. 3-word nav
# stubs, error pages, robots.txt-blocked excerpt.
MIN_WORD_COUNT = 200

# Hard floor below which "best-effort" returns are suppressed entirely.
# A paywall stub usually carries 30-150 words of preview, which is
# legitimately useful even though it's below MIN_WORD_COUNT. A 3-word
# "About Blog Contact" extract from a nav page is not. The 20-word
# floor draws the line where it actually matters.
HARD_FLOOR_WORDS = 20

# httpx defaults are generous; we time out faster so a stalled host
# doesn't lock up the orchestrator. Five seconds to connect, fifteen
# to read — same shape the social connectors use.
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

_USER_AGENT = (
    "pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani; article-extraction)"
)


@dataclass
class ExtractionResult:
    """Clean-text + metadata bundle produced by :func:`extract_text`.

    Field shapes match what the chunking + embedding pipeline expects.
    Missing-but-recoverable values default to ``None`` / empty string
    so callers can use them as Chroma metadata without further
    coercion (Chroma metadata only stores flat primitives).

    `text` is the canonical output — boilerplate-stripped article body
    with paragraph breaks preserved as ``\\n\\n``. The chunker will
    further sentence-split this on the way to RAG indexing.

    `source` records which extraction path produced this result:
      - ``"trafilatura"`` — static HTML extraction (the common case).
      - ``"playwright"`` — JS-rendered DOM extraction (future fallback).
      - ``"manual"`` — caller supplied raw text (paste-mode, S-1.5.8).
    """

    text: str
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    language: str | None = None
    word_count: int = 0
    source: str = "trafilatura"
    extra: dict[str, Any] = field(default_factory=dict)


def _fetch_html(url: str) -> str | None:
    """GET ``url`` and return the raw HTML body.

    Returns ``None`` on any HTTP failure or non-2xx response. Callers
    treat None as "extraction failed, document unavailable" — same
    contract every other connector uses for fail-soft.
    """
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        logger.warning("article-extraction fetch failed for %s: %s", url, e)
        return None

    if resp.status_code >= 400:
        logger.warning(
            "article-extraction fetch returned %s for %s",
            resp.status_code,
            url,
        )
        return None
    return resp.text


def _parse_iso(value: str | None) -> datetime | None:
    """Parse a trafilatura-emitted publication date.

    Trafilatura emits ``YYYY-MM-DD`` (or ``YYYY-MM-DDTHH:MM:SS+ZZ:ZZ``
    when the page exposes a precise timestamp). We tolerate both.
    Anything unparseable returns ``None`` rather than raising, so
    a malformed date doesn't poison the whole extraction.
    """
    if not value:
        return None
    try:
        # Try ISO datetime first (with tz / time component).
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass
    try:
        # Fall back to date-only.
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _trafilatura_extract(url: str, html: str) -> ExtractionResult | None:
    """Run trafilatura against pre-fetched HTML; return result or None.

    Uses ``output_format="json"`` so we get the metadata block alongside
    the body text in a single call (without it we'd need a second pass
    through ``extract_metadata``). Trafilatura's JSON output keys we
    rely on: ``text``, ``title``, ``author``, ``date``, ``language``.
    """
    try:
        # `extract` returns a JSON string when output_format='json'.
        raw = trafilatura.extract(
            html,
            url=url,
            output_format="json",
            with_metadata=True,
            include_comments=False,  # comment threads are noise for articles
            include_tables=True,  # tables often carry article data
            favor_precision=True,  # prefer dropping marginal text over including boilerplate
        )
    except Exception as e:
        # Trafilatura can raise on truly malformed HTML; treat as
        # extraction failure rather than crashing the orchestrator.
        logger.warning(
            "trafilatura raised on %s: %s",
            url,
            e,
        )
        return None
    if not raw:
        return None
    import json

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "trafilatura returned non-JSON for %s; skipping",
            url,
        )
        return None
    if not isinstance(payload, dict):
        return None

    text = (payload.get("text") or "").strip()
    if not text:
        return None
    word_count = len(text.split())
    return ExtractionResult(
        text=text,
        title=(payload.get("title") or None),
        author=(payload.get("author") or None),
        published_at=_parse_iso(payload.get("date")),
        language=(payload.get("language") or None),
        word_count=word_count,
        source="trafilatura",
        extra={
            k: payload[k]
            for k in ("hostname", "sitename", "categories", "tags")
            if k in payload and payload[k]
        },
    )


def _playwright_fallback(url: str) -> ExtractionResult | None:
    """SPA-rendered DOM fallback — currently a structurally-present stub.

    The full article connector (E-1.6 follow-up) ships a Playwright
    integration here: launch headless Chromium, navigate, wait for
    hydration (network-idle + DOM-stable heuristic), grab the
    rendered HTML, feed it through trafilatura. We don't ship that
    today because:

    1. Playwright pulls ~150MB of Chromium binaries that would
       weigh down the default backend install for users who don't
       need SPA support.
    2. The opt-in install pattern (``pip install pratidhvani[spa]``
       extra) needs to land alongside the orchestrator code that
       triggers it.

    **Opt-in.** Gated on ``settings.ARTICLE_PLAYWRIGHT_ENABLED``
    (default ``False``). Default install doesn't include `playwright`
    or Chromium binaries (~150MB). Operators who want SPA support
    install via ``pip install -r backend/requirements-spa.txt`` then
    ``playwright install chromium``, and flip the env var.

    **Fail-soft.** If `playwright` isn't importable, Chromium isn't
    installed, the page errors, or hydration times out, returns
    ``None`` with an INFO log — same contract as `extract_text` itself.
    Never raises.
    """
    if not settings.ARTICLE_PLAYWRIGHT_ENABLED:
        logger.info(
            "Playwright fallback disabled (ARTICLE_PLAYWRIGHT_ENABLED=False) "
            "for %s; returning None. To enable, install "
            "`backend/requirements-spa.txt` + `playwright install chromium`.",
            url,
        )
        return None

    # Lazy import — playwright is opt-in. If it's not installed, fall
    # through gracefully rather than crashing import of the extractor
    # module on hosts that don't need SPA support.
    try:
        from playwright.sync_api import (
            Error as PlaywrightError,
            TimeoutError as PlaywrightTimeoutError,
            sync_playwright,
        )
    except ImportError:
        logger.info(
            "Playwright fallback enabled but `playwright` package isn't "
            "installed for %s; returning None. Run `pip install -r "
            "backend/requirements-spa.txt`.",
            url,
        )
        return None

    timeout_ms = max(1000, settings.ARTICLE_PLAYWRIGHT_TIMEOUT_SEC * 1000)
    rendered_html: str | None = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=_USER_AGENT,
                    java_script_enabled=True,
                )
                page = context.new_page()
                # `wait_until="networkidle"` is the strongest heuristic
                # for "hydration complete" — the page has stopped
                # issuing XHRs. Some SPAs poll indefinitely; the
                # timeout floor caps that case so we don't stall
                # the orchestrator.
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                rendered_html = page.content()
            finally:
                browser.close()
    except PlaywrightTimeoutError as e:
        logger.info(
            "Playwright fallback timed out (%ds) for %s: %s",
            settings.ARTICLE_PLAYWRIGHT_TIMEOUT_SEC,
            url,
            e,
        )
        return None
    except PlaywrightError as e:
        logger.info(
            "Playwright fallback Playwright-error for %s: %s",
            url,
            e,
        )
        return None
    except Exception as e:
        # Defensive — Playwright sometimes raises non-Playwright
        # exception types on platform-specific edge cases (e.g.
        # subprocess errors on Windows when Chromium binaries are
        # corrupt). Log + None.
        logger.info(
            "Playwright fallback unexpected error for %s: %s",
            url,
            e,
        )
        return None

    if not rendered_html:
        return None

    # Re-feed the rendered HTML through trafilatura. The result, if
    # any, is tagged ``source='playwright'`` so callers / tests can
    # distinguish primary from fallback.
    primary = _trafilatura_extract(url, rendered_html)
    if primary is None:
        return None
    primary.source = "playwright"
    return primary


def extract_text(url: str) -> ExtractionResult | None:
    """Extract clean article text from ``url``.

    Hybrid strategy:

    1. Fetch the raw HTML via httpx (User-Agent set, follow redirects).
    2. Run trafilatura. If it returns text with at least
       :data:`MIN_WORD_COUNT` words, return that result.
    3. Otherwise, invoke the Playwright fallback (currently a stub).

    Returns ``None`` when both paths fail. The orchestrator treats
    None as "document unavailable" rather than crashing the job.

    Args:
        url: Absolute HTTP/HTTPS URL of the article. Relative paths,
            ``file://``, or other schemes are rejected by httpx and
            surface as a warning + None.

    Returns:
        :class:`ExtractionResult` on success, ``None`` on failure.
    """
    if not url or not isinstance(url, str):
        logger.warning("extract_text: invalid url %r", url)
        return None

    html = _fetch_html(url)
    if not html:
        # HTTP-level failure — Playwright fallback wouldn't help on
        # an unreachable URL, so short-circuit here.
        return None

    primary = _trafilatura_extract(url, html)
    if primary is not None and primary.word_count >= MIN_WORD_COUNT:
        return primary

    # Either trafilatura returned nothing (likely SPA shell), or it
    # returned a too-short result (likely paywall stub or navigation
    # page). Try the Playwright fallback.
    fallback = _playwright_fallback(url)
    if fallback is not None and fallback.word_count >= MIN_WORD_COUNT:
        return fallback

    # If trafilatura got something but it was below the threshold,
    # surface that as the best-effort result IF the fallback also
    # failed — better to return a short article than nothing for a
    # paywall stub case where the user wants the partial text.
    # BUT: enforce a hard floor (`HARD_FLOOR_WORDS`) below which the
    # extract is almost certainly nav-chrome / error-page noise and
    # would just pollute the library.
    if primary is not None and primary.word_count >= HARD_FLOOR_WORDS:
        logger.info(
            "extract_text: trafilatura yielded only %d words for %s "
            "(below MIN_WORD_COUNT=%d); returning anyway as best-effort",
            primary.word_count,
            url,
            MIN_WORD_COUNT,
        )
        return primary

    if primary is not None:
        logger.info(
            "extract_text: trafilatura yielded only %d words for %s "
            "(below HARD_FLOOR_WORDS=%d); treating as failure",
            primary.word_count,
            url,
            HARD_FLOOR_WORDS,
        )

    return None
