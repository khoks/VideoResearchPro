"""Unit tests for `app.services.connector_dispatch` — S-1.5.11 T-1.5.11.1.

The dispatcher is the search-phase fan-out for multi-source topic
jobs. Each source_type's connector is invoked through the registry
(`connector_for(source_type)`); failures are caught per-source-type
so one connector's outage doesn't crash the whole job.

Strategy: register fake connectors via `registry._reset_for_tests()`
+ `registry.register(...)`, then drive `dispatch_search()` and
assert on the `DispatchResult` shape.
"""
from __future__ import annotations

import pytest

from app.services.connector_dispatch import DispatchResult, dispatch_search
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.types import Candidate


# ---------------------------------------------------------------------------
# Fake connectors
# ---------------------------------------------------------------------------
class _SuccessConnector(BaseConnector):
    """Always returns the configured candidates."""

    def __init__(self, source_type: str, candidates: list[Candidate]):
        self.source_type = source_type
        self._candidates = candidates
        self.last_call: dict | None = None

    def search(self, query: str, instructions: str = "", limit: int = 10):
        self.last_call = {"query": query, "instructions": instructions, "limit": limit}
        return self._candidates[:limit]

    def list_creator_items(self, *args, **kwargs):  # pragma: no cover — unused
        return []

    def fetch_metadata(self, *args, **kwargs):  # pragma: no cover — unused
        return {}

    def fetch_text(self, *args, **kwargs):  # pragma: no cover — unused
        return None


class _RaisingConnector(BaseConnector):
    """Raises whenever search() is called — to test fail-isolation."""

    def __init__(self, source_type: str, exc: Exception):
        self.source_type = source_type
        self._exc = exc

    def search(self, *args, **kwargs):
        raise self._exc

    def list_creator_items(self, *args, **kwargs):  # pragma: no cover
        return []

    def fetch_metadata(self, *args, **kwargs):  # pragma: no cover
        return {}

    def fetch_text(self, *args, **kwargs):  # pragma: no cover
        return None


class _NotImplementedConnector(BaseConnector):
    """Raises NotImplementedError on search() — PDF-style."""

    def __init__(self, source_type: str):
        self.source_type = source_type

    def search(self, *args, **kwargs):
        raise NotImplementedError("This connector doesn't support search")

    def list_creator_items(self, *args, **kwargs):  # pragma: no cover
        return []

    def fetch_metadata(self, *args, **kwargs):  # pragma: no cover
        return {}

    def fetch_text(self, *args, **kwargs):  # pragma: no cover
        return None


def _candidate(source_type: str, source_id: str, title: str = "") -> Candidate:
    return Candidate(
        source_type=source_type,
        source_id=source_id,
        title=title or f"{source_type} {source_id}",
        source_url=f"https://example.test/{source_type}/{source_id}",
    )


# ---------------------------------------------------------------------------
# Fixture: clean registry per test, restored after
# ---------------------------------------------------------------------------
@pytest.fixture
def clean_registry():
    """Snapshot registry state, swap in clean state, restore afterwards
    so tests can inject fakes without leaking between tests."""
    snapshot = registry.all_connectors()
    registry._reset_for_tests()
    yield
    registry._reset_for_tests()
    for c in snapshot.values():
        registry.register(c)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_dispatch_search_returns_candidates_per_source_type(clean_registry):
    video = _SuccessConnector("video", [_candidate("video", f"v{i}") for i in range(3)])
    reddit = _SuccessConnector(
        "reddit_post", [_candidate("reddit_post", f"reddit:r{i}") for i in range(2)]
    )
    registry.register(video)
    registry.register(reddit)

    result = dispatch_search(
        ["video", "reddit_post"],
        query="tariffs",
        instructions="focus on macro angles",
        limit_per_type=10,
        job_id="job-1",
    )

    assert isinstance(result, DispatchResult)
    assert len(result.candidates_by_source_type["video"]) == 3
    assert len(result.candidates_by_source_type["reddit_post"]) == 2
    assert result.errors_by_source_type == {}
    assert result.total_count == 5
    assert not result.has_errors


def test_dispatch_search_passes_query_and_instructions_to_each_connector(
    clean_registry,
):
    video = _SuccessConnector("video", [_candidate("video", "v1")])
    reddit = _SuccessConnector("reddit_post", [_candidate("reddit_post", "reddit:r1")])
    registry.register(video)
    registry.register(reddit)

    dispatch_search(
        ["video", "reddit_post"],
        query="quantum computing",
        instructions="prefer experts",
        limit_per_type=5,
    )

    assert video.last_call == {
        "query": "quantum computing",
        "instructions": "prefer experts",
        "limit": 5,
    }
    assert reddit.last_call == {
        "query": "quantum computing",
        "instructions": "prefer experts",
        "limit": 5,
    }


def test_dispatch_search_preserves_source_type_order(clean_registry):
    """`all_candidates()` returns candidates in the order source_types
    were dispatched, regardless of how the registry stored them."""
    a = _SuccessConnector("video", [_candidate("video", "vA")])
    b = _SuccessConnector("reddit_post", [_candidate("reddit_post", "reddit:rA")])
    c = _SuccessConnector("hn_story", [_candidate("hn_story", "hn:hA")])
    registry.register(c)  # register out of order on purpose
    registry.register(a)
    registry.register(b)

    result = dispatch_search(["hn_story", "video", "reddit_post"], query="x")
    flat = result.all_candidates()

    assert [c.source_type for c in flat] == ["hn_story", "video", "reddit_post"]


# ---------------------------------------------------------------------------
# Error isolation
# ---------------------------------------------------------------------------
def test_dispatch_search_isolates_a_connector_failure(clean_registry):
    """One connector raising must not crash; others' results survive."""
    good = _SuccessConnector("video", [_candidate("video", "v1")])
    bad = _RaisingConnector("reddit_post", RuntimeError("reddit on fire"))
    registry.register(good)
    registry.register(bad)

    result = dispatch_search(["video", "reddit_post"], query="x", job_id="job-99")

    assert len(result.candidates_by_source_type["video"]) == 1
    assert result.candidates_by_source_type["reddit_post"] == []
    assert "reddit_post" in result.errors_by_source_type
    assert "RuntimeError" in result.errors_by_source_type["reddit_post"]
    assert "reddit on fire" in result.errors_by_source_type["reddit_post"]
    assert result.has_errors


def test_dispatch_search_records_missing_connector_as_error(clean_registry):
    """No connector for the requested source_type → error captured, no raise."""
    only_video = _SuccessConnector("video", [_candidate("video", "v1")])
    registry.register(only_video)

    result = dispatch_search(["video", "mastodon_post"], query="x")

    assert len(result.candidates_by_source_type["video"]) == 1
    assert result.candidates_by_source_type["mastodon_post"] == []
    assert "mastodon_post" in result.errors_by_source_type
    assert result.has_errors


def test_dispatch_search_treats_not_implemented_as_zero_candidates(clean_registry):
    """A connector that legitimately doesn't support search (PDF, etc.)
    yields zero candidates with NO error logged."""
    pdf_like = _NotImplementedConnector("pdf")
    video = _SuccessConnector("video", [_candidate("video", "v1")])
    registry.register(pdf_like)
    registry.register(video)

    result = dispatch_search(["video", "pdf"], query="x")

    assert result.candidates_by_source_type["pdf"] == []
    assert "pdf" not in result.errors_by_source_type
    assert not result.has_errors  # NotImplementedError isn't a degraded-mode signal


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
def test_dispatch_search_empty_source_types_returns_empty_result(clean_registry):
    """An empty source_types list is a no-op — useful for orchestrator
    code paths that compute source_types dynamically."""
    result = dispatch_search([], query="x")

    assert result.total_count == 0
    assert result.candidates_by_source_type == {}
    assert result.errors_by_source_type == {}
    assert not result.has_errors


def test_dispatch_search_respects_limit_per_type(clean_registry):
    """`limit_per_type` is forwarded as `limit` to each connector's search()."""
    video = _SuccessConnector(
        "video", [_candidate("video", f"v{i}") for i in range(20)]
    )
    registry.register(video)

    result = dispatch_search(["video"], query="x", limit_per_type=5)

    assert len(result.candidates_by_source_type["video"]) == 5
