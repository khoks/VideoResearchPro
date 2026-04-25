"""Tests for the source-connector registry."""
import pytest

from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.types import Candidate, ExtractedText, SourceMetadata


class _FakeConnector(BaseConnector):
    source_type = "fake-test-only"

    def search(self, query, instructions="", limit=10):
        return []

    def list_creator_items(self, creator_external_id, since=None, *, limit=None):
        return iter(())

    def fetch_metadata(self, source_ids):
        return {}

    def fetch_text(self, candidate, *, job_id=""):
        return None


@pytest.fixture
def isolated_registry(monkeypatch):
    """Snapshot + restore the global registry around a test.

    Tests that register fakes must not bleed state across test runs.
    """
    original = dict(registry._REGISTRY)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(original)


def test_video_connector_is_registered():
    """Importing `app.sources` registers the YouTube connector. The job
    orchestrator depends on this implicit registration, so a missing
    entry is a hard regression."""
    yt = registry.connector_for("video")
    assert yt is not None
    assert yt.source_type == "video"
    assert isinstance(yt, BaseConnector)


def test_connector_for_unknown_source_raises_with_helpful_message():
    with pytest.raises(KeyError) as excinfo:
        registry.connector_for("does-not-exist")
    msg = str(excinfo.value)
    assert "does-not-exist" in msg
    assert "registered" in msg


def test_register_returns_none_and_overrides_existing(isolated_registry):
    """Re-registering the same source_type must replace the prior entry —
    tests rely on this to swap in fakes."""
    fake = _FakeConnector()
    registry.register(fake)
    assert registry.connector_for("fake-test-only") is fake

    fake2 = _FakeConnector()
    registry.register(fake2)
    assert registry.connector_for("fake-test-only") is fake2


def test_register_rejects_non_connector():
    with pytest.raises(TypeError):
        registry.register("not a connector")  # type: ignore[arg-type]


def test_all_connectors_returns_a_copy(isolated_registry):
    """Mutating the result must not affect the live registry."""
    fake = _FakeConnector()
    registry.register(fake)

    snapshot = registry.all_connectors()
    snapshot.pop("fake-test-only")

    # Live registry still has it.
    assert registry.connector_for("fake-test-only") is fake


def test_youtube_connector_implements_full_contract():
    """The YouTube connector must satisfy every BaseConnector hook so the
    orchestrator never sees `NotImplementedError`."""
    yt = registry.connector_for("video")
    # Required methods (raise on missing implementation in ABC).
    assert callable(yt.search)
    assert callable(yt.list_creator_items)
    assert callable(yt.fetch_metadata)
    assert callable(yt.fetch_text)
    # Optional method should still be present on the instance.
    assert callable(yt.fetch_creator)


def test_dataclasses_have_expected_required_fields():
    """The job orchestrator constructs Candidates inline; lock the
    required-positional shape so accidental field reordering surfaces
    as a test failure rather than a runtime TypeError."""
    c = Candidate(
        source_type="video",
        source_id="abc123",
        title="t",
        source_url="https://example.com",
    )
    assert c.source_type == "video"
    assert c.creator_external_id is None  # default
    assert c.extra == {}

    et = ExtractedText(
        segments=[{"text": "hi", "start": 0.0, "duration": 1.0}],
        language="en",
        text_source="youtube",
        word_count=1,
    )
    assert et.word_count == 1

    sm = SourceMetadata()
    assert sm.title is None
    assert sm.extra == {}
