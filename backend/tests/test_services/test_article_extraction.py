"""Unit tests for `app.services.article_extraction`.

Strategy: avoid network calls. We patch `httpx.get` to return a fixture
HTML body, then assert that the trafilatura primary path produces the
expected `ExtractionResult` shape. Playwright fallback is a stub today
and tested behaviorally (returns None, doesn't crash, doesn't fabricate).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import httpx
import pytest

from app.services.article_extraction import (
    MIN_WORD_COUNT,
    ExtractionResult,
    extract_text,
)


# ---------------------------------------------------------------------------
# Fixture HTML — small, well-formed article shapes
# ---------------------------------------------------------------------------

# A typical longform blog post with title / author / date metadata in
# meta tags. Trafilatura handles this shape well.
ARTICLE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>The Future of Software Development</title>
  <meta name="author" content="Jane Doe">
  <meta property="article:published_time" content="2024-03-15T10:30:00Z">
  <meta property="og:title" content="The Future of Software Development">
</head>
<body>
  <header>
    <nav>Home | About | Archive</nav>
  </header>
  <article>
    <h1>The Future of Software Development</h1>
    <p>Software development is undergoing a fundamental shift driven by
    the integration of large language models into every layer of the
    development workflow. From code generation to code review, from
    refactoring to testing, the practitioner's daily experience is
    being remade in real time. This essay explores three trends that
    will define the next five years.</p>

    <p>The first trend is the move from autocomplete to autonomous
    agents. Early code-completion tools predicted the next token; the
    new generation of agents read a ticket, plan a series of changes,
    execute them across multiple files, run tests, and iterate when
    something breaks. The boundary between "tool" and "collaborator"
    is genuinely blurring, and the implications for team structure
    are profound.</p>

    <p>The second trend is the rise of polyglot architectures with
    LLM-mediated translation between languages. When a model can read
    Python and emit Rust with high fidelity, the cost of choosing the
    "right" language for a given subsystem drops dramatically. We
    expect to see more services rewritten in compiled languages for
    performance-critical paths, with the original prototype kept as a
    living spec.</p>

    <p>The third trend is the shift from documentation as a static
    artifact to documentation as a queryable surface. The team's
    knowledge — design decisions, debugging sessions, code reviews —
    becomes a corpus that the LLM consults rather than a wiki the
    developer searches. This changes how onboarding works, how
    knowledge is preserved when senior engineers leave, and how new
    architectural choices are evaluated against historical context.</p>
  </article>
  <footer>Copyright 2024. All rights reserved.</footer>
</body>
</html>
"""

# A shell page that would be rendered by JS at runtime — trafilatura
# will see only the empty body. This is the case where the Playwright
# fallback would (eventually) kick in.
SPA_SHELL_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Loading…</title>
</head>
<body>
  <div id="root"></div>
  <script src="/static/app.bundle.js"></script>
</body>
</html>
"""

# A paywall stub — short article preview followed by a subscribe CTA.
# Trafilatura extracts the preview but it's too short to be useful.
PAYWALL_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <title>Behind the Paywall</title>
  <meta name="author" content="Anon">
</head>
<body>
  <article>
    <h1>Behind the Paywall</h1>
    <p>This article is for subscribers only. Here's a short preview
    of what awaits inside.</p>
    <p>Subscribe to read more.</p>
  </article>
</body>
</html>
"""

# A page with no extractable content — only navigation chrome.
NAV_PAGE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><title>Home</title></head>
<body>
  <nav>
    <a href="/about">About</a>
    <a href="/blog">Blog</a>
    <a href="/contact">Contact</a>
  </nav>
</body>
</html>
"""


def _mock_response(html: str, status: int = 200) -> Mock:
    """Build a `httpx.Response`-like mock returning `html` as `.text`."""
    resp = Mock(spec=httpx.Response)
    resp.text = html
    resp.status_code = status
    return resp


# ---------------------------------------------------------------------------
# Trafilatura primary path
# ---------------------------------------------------------------------------


def test_extract_text_returns_extraction_result_for_typical_article():
    """A well-formed longform article: trafilatura extracts body, title,
    author, date — the four fields most callers need."""
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        return_value=_mock_response(ARTICLE_HTML),
    ):
        result = extract_text("https://example.com/future-of-software")

    assert isinstance(result, ExtractionResult)
    assert "Software development" in result.text
    # Three of the four article paragraphs are full sentences ending
    # with a period; trafilatura should have all three plus the first
    # paragraph's content.
    assert "language models" in result.text
    assert "polyglot architectures" in result.text
    assert "queryable surface" in result.text
    assert result.title == "The Future of Software Development"
    assert result.author == "Jane Doe"
    assert result.word_count >= 200  # comfortably above MIN_WORD_COUNT


def test_extract_text_parses_publication_date_to_utc_datetime():
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        return_value=_mock_response(ARTICLE_HTML),
    ):
        result = extract_text("https://example.com/future-of-software")
    assert result is not None
    # Trafilatura emits the date as YYYY-MM-DD — we tolerate both that
    # and the full ISO timestamp the page carries. Either way, we
    # should land on the right calendar date.
    assert result.published_at is not None
    assert result.published_at.year == 2024
    assert result.published_at.month == 3
    assert result.published_at.day == 15


def test_extract_text_records_source_as_trafilatura_for_static_html():
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        return_value=_mock_response(ARTICLE_HTML),
    ):
        result = extract_text("https://example.com/x")
    assert result is not None
    assert result.source == "trafilatura"


# ---------------------------------------------------------------------------
# Below-threshold + fallback handling
# ---------------------------------------------------------------------------


def test_extract_text_returns_short_article_as_best_effort_when_below_threshold():
    """A paywall stub: trafilatura extracts a few sentences (well below
    MIN_WORD_COUNT). Today the Playwright fallback is a stub returning
    None, so we surface the partial extract rather than dropping the
    document entirely. Caller can decide whether to keep it or
    re-classify the source as paywalled."""
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        return_value=_mock_response(PAYWALL_HTML),
    ):
        result = extract_text("https://paywall.example.com/article")

    # Best-effort: trafilatura got something, fallback failed, we
    # return what we have rather than None.
    assert result is not None
    assert result.word_count < MIN_WORD_COUNT
    assert "preview" in result.text.lower()


def test_extract_text_returns_none_when_extraction_fully_fails():
    """Pure-navigation page: trafilatura finds nothing, fallback stub
    returns None, overall result is None."""
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        return_value=_mock_response(NAV_PAGE_HTML),
    ):
        result = extract_text("https://example.com/")
    assert result is None


def test_extract_text_returns_none_for_spa_shell_today():
    """SPA shell — trafilatura sees no article body. Playwright fallback
    is a stub today (returns None) so the overall result is None.
    Future PR replaces the stub with real Playwright; this test
    will then need to be updated to assert a non-None result."""
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        return_value=_mock_response(SPA_SHELL_HTML),
    ):
        result = extract_text("https://spa.example.com/")
    assert result is None


# ---------------------------------------------------------------------------
# HTTP failure modes
# ---------------------------------------------------------------------------


def test_extract_text_returns_none_on_http_4xx():
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        return_value=_mock_response("Not Found", status=404),
    ):
        assert extract_text("https://example.com/missing") is None


def test_extract_text_returns_none_on_http_5xx():
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        return_value=_mock_response("Server Error", status=503),
    ):
        assert extract_text("https://example.com/down") is None


def test_extract_text_returns_none_on_httpx_error():
    """Network errors (DNS failure, connection reset, timeout) must
    degrade to None rather than crashing the orchestrator."""
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        side_effect=httpx.ConnectError("dns failed"),
    ):
        assert extract_text("https://nonexistent.example/") is None


def test_extract_text_returns_none_on_invalid_url_input():
    """Defensive — empty / None / non-string inputs short-circuit
    before attempting the network call."""
    assert extract_text("") is None
    assert extract_text(None) is None  # type: ignore[arg-type]
    assert extract_text(123) is None  # type: ignore[arg-type]


def test_extract_text_sets_user_agent_header():
    """Polite User-Agent so operators can identify us in their logs."""
    captured: dict = {}

    def _capture_get(url, **kwargs):
        captured["headers"] = kwargs.get("headers", {})
        return _mock_response(ARTICLE_HTML)

    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        side_effect=_capture_get,
    ):
        extract_text("https://example.com/x")

    assert "User-Agent" in captured["headers"]
    assert "pratidhvani" in captured["headers"]["User-Agent"]


def test_extract_text_follows_redirects():
    """Articles often redirect (canonical URL forwarding, www → non-
    www, http → https). httpx must follow them so the trafilatura
    pass sees the final body."""
    captured: dict = {}

    def _capture_get(url, **kwargs):
        captured["follow_redirects"] = kwargs.get("follow_redirects")
        return _mock_response(ARTICLE_HTML)

    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        side_effect=_capture_get,
    ):
        extract_text("https://example.com/x")

    assert captured["follow_redirects"] is True


# ---------------------------------------------------------------------------
# Defensive trafilatura handling
# ---------------------------------------------------------------------------


def test_extract_text_handles_trafilatura_returning_none(monkeypatch):
    """Trafilatura can return None on truly malformed input; the
    extractor must treat that as 'no result' rather than crashing."""
    monkeypatch.setattr(
        "app.services.article_extraction.extractor.trafilatura.extract",
        lambda *a, **k: None,
    )
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        return_value=_mock_response("<html><body>Hello</body></html>"),
    ):
        assert extract_text("https://example.com/x") is None


def test_extract_text_handles_trafilatura_returning_non_json(monkeypatch):
    """Belt-and-braces — if trafilatura's `output_format='json'` ever
    returns non-JSON (we've seen this in older versions on edge-case
    HTML), we log + fall through rather than raising."""
    monkeypatch.setattr(
        "app.services.article_extraction.extractor.trafilatura.extract",
        lambda *a, **k: "this is not JSON",
    )
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        return_value=_mock_response("<html><body>Hello</body></html>"),
    ):
        assert extract_text("https://example.com/x") is None


def test_extract_text_handles_trafilatura_raising(monkeypatch):
    """Trafilatura can raise on truly broken HTML — the extractor's
    fail-soft contract says any extraction failure → None, never a
    bubbled exception."""
    def _boom(*a, **k):
        raise RuntimeError("trafilatura blew up")

    monkeypatch.setattr(
        "app.services.article_extraction.extractor.trafilatura.extract",
        _boom,
    )
    with patch(
        "app.services.article_extraction.extractor.httpx.get",
        return_value=_mock_response("<html><body>Hello</body></html>"),
    ):
        assert extract_text("https://example.com/x") is None


# ---------------------------------------------------------------------------
# ExtractionResult shape
# ---------------------------------------------------------------------------


def test_extraction_result_default_source_is_trafilatura():
    er = ExtractionResult(text="Hello", word_count=1)
    assert er.source == "trafilatura"
    assert er.extra == {}
    assert er.author is None
    assert er.published_at is None


def test_extraction_result_supports_manual_paste_source():
    """Manual-paste mode (S-1.5.8) will construct ExtractionResult
    directly with `source='manual'` rather than going through
    `extract_text`. Lock that path is supported."""
    er = ExtractionResult(
        text="User-pasted body",
        word_count=3,
        source="manual",
        title="Pasted Title",
    )
    assert er.source == "manual"
    assert er.title == "Pasted Title"


def test_extract_text_published_at_handles_date_only_format():
    """Trafilatura sometimes emits `YYYY-MM-DD` (no time component).
    The parser must accept both forms."""
    # We stub trafilatura to return JSON with a date-only string.
    with (
        patch(
            "app.services.article_extraction.extractor.httpx.get",
            return_value=_mock_response("<html><body>Body</body></html>"),
        ),
        patch(
            "app.services.article_extraction.extractor.trafilatura.extract",
            return_value=(
                '{"text": "Plenty of words here. ' + "word " * 250 + '",'
                ' "title": "T", "author": "A", "date": "2023-06-01",'
                ' "language": "en"}'
            ),
        ),
    ):
        result = extract_text("https://example.com/x")

    assert result is not None
    assert result.published_at == datetime(2023, 6, 1)


def test_extract_text_published_at_handles_full_iso_format():
    with (
        patch(
            "app.services.article_extraction.extractor.httpx.get",
            return_value=_mock_response("<html><body>Body</body></html>"),
        ),
        patch(
            "app.services.article_extraction.extractor.trafilatura.extract",
            return_value=(
                '{"text": "Plenty of words. ' + "word " * 250 + '",'
                ' "title": "T", "date": "2023-06-01T15:30:00Z"}'
            ),
        ),
    ):
        result = extract_text("https://example.com/x")

    assert result is not None
    assert result.published_at is not None
    assert result.published_at.year == 2023
    assert result.published_at.tzinfo is not None  # tz-aware


def test_extract_text_published_at_returns_none_for_unparseable():
    with (
        patch(
            "app.services.article_extraction.extractor.httpx.get",
            return_value=_mock_response("<html><body>Body</body></html>"),
        ),
        patch(
            "app.services.article_extraction.extractor.trafilatura.extract",
            return_value=(
                '{"text": "Plenty. ' + "word " * 250 + '",'
                ' "title": "T", "date": "yesterday-ish"}'
            ),
        ),
    ):
        result = extract_text("https://example.com/x")

    assert result is not None
    assert result.published_at is None  # gracefully drops bad date
