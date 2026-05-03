"""Unit tests for the Mastodon connector + flatten + client.

Strategy mirrors `test_hn_connector.py` and `test_reddit_connector.py`:
mock the underlying client so we lock down the *shape transformation*
(Mastodon JSON → typed dataclasses) and *wiring* (which client method
each connector method calls), not the upstream API behavior.

The connector reads the singleton via ``mastodon_client.get_client()``;
tests patch that attribute on the imported module to inject a
``unittest.mock.Mock`` with the wrapper methods.
"""
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from app.sources import registry
from app.sources.mastodon import client as mastodon_client_mod
from app.sources.mastodon import connector as mastodon_connector_mod
from app.sources.mastodon import flatten as mastodon_flatten
from app.sources.mastodon.client import MastodonClient
from app.sources.mastodon.connector import (
    MastodonConnector,
    _topic_to_hashtag,
)
from app.sources.types import Candidate, ExtractedText, SourceMetadata


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def mast():
    return MastodonConnector()


@pytest.fixture
def fake_client():
    """A Mock standing in for `MastodonClient`. Patch `get_client` to
    return this fixture when the connector calls into the singleton."""
    return Mock(spec=MastodonClient)


def _account(
    user: str = "alice",
    instance: str = "",
    display_name: str = "Alice",
    account_id: str = "user-1",
) -> dict:
    """Build an account dict matching Mastodon's `/accounts/...` shape."""
    if instance:
        acct = f"{user}@{instance}"
    else:
        acct = user
    return {
        "id": account_id,
        "username": user,
        "acct": acct,
        "display_name": display_name,
    }


def _status(
    status_id: str = "100",
    content: str = "<p>A status body.</p>",
    account: dict | None = None,
    created_at: str = "2024-01-15T12:00:00.000Z",
    favourites: int = 5,
    reblogs: int = 2,
    replies: int = 3,
    url: str | None = None,
    in_reply_to_id: str | None = None,
    language: str = "en",
    media: list | None = None,
) -> dict:
    """Build a status dict matching Mastodon's `/statuses/<id>` shape."""
    if account is None:
        account = _account()
    return {
        "id": status_id,
        "content": content,
        "account": account,
        "created_at": created_at,
        "favourites_count": favourites,
        "reblogs_count": reblogs,
        "replies_count": replies,
        "url": url or f"https://mastodon.social/@{account.get('acct')}/{status_id}",
        "in_reply_to_id": in_reply_to_id,
        "language": language,
        "media_attachments": media or [],
    }


def _context(descendants: list[dict] | None = None, ancestors: list[dict] | None = None) -> dict:
    return {
        "ancestors": ancestors or [],
        "descendants": descendants or [],
    }


# ---------------------------------------------------------------------------
# _topic_to_hashtag normalisation
# ---------------------------------------------------------------------------
def test_topic_to_hashtag_strips_spaces_and_punctuation():
    assert _topic_to_hashtag("climate change") == "climatechange"
    assert _topic_to_hashtag("Hello, World!") == "helloworld"
    assert _topic_to_hashtag("AI/ML") == "aiml"


def test_topic_to_hashtag_lowercases():
    assert _topic_to_hashtag("ClimateChange") == "climatechange"
    assert _topic_to_hashtag("FreeSoftware") == "freesoftware"


def test_topic_to_hashtag_handles_unicode_letters():
    """Mastodon hashtags accept Unicode letters/digits — keep CJK / Devanagari /
    accented chars rather than dropping them."""
    assert _topic_to_hashtag("परिवर्तन") == "परिवर्तन"
    assert _topic_to_hashtag("café") == "café"


def test_topic_to_hashtag_empty_when_only_punctuation():
    """Pure-punctuation queries yield empty strings — caller treats as
    'no hashtag, skip search'."""
    assert _topic_to_hashtag("---!!") == ""
    assert _topic_to_hashtag("") == ""


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------
def test_search_calls_timeline_tag_with_normalised_hashtag(mast, fake_client):
    fake_client.timeline_tag.return_value = [
        _status(status_id="100", content="<p>Body</p>"),
    ]
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.search("Climate Change", instructions="ignored", limit=5)

    fake_client.timeline_tag.assert_called_once_with("climatechange", limit=5)
    assert len(out) == 1
    c = out[0]
    assert isinstance(c, Candidate)
    assert c.source_type == "mastodon_post"
    assert c.source_id == "mastodon:100"
    assert c.creator_external_id == "alice"
    assert c.creator_name == "Alice"
    assert c.source_url.startswith("https://mastodon.social")


def test_search_returns_empty_when_normalised_query_is_blank(mast, fake_client):
    """Pure-punctuation queries shouldn't trigger an HTTP call."""
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.search("---!!!")
    assert out == []
    fake_client.timeline_tag.assert_not_called()


def test_search_returns_empty_when_timeline_raises(mast, fake_client):
    """Connector failures during search must degrade to empty list — the
    dispatcher catches connector errors but search() itself shouldn't bubble."""
    fake_client.timeline_tag.side_effect = RuntimeError("instance down")
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.search("anything")
    assert out == []


def test_search_published_at_is_utc(mast, fake_client):
    fake_client.timeline_tag.return_value = [
        _status(status_id="t1", created_at="2024-01-15T12:00:00.000Z"),
    ]
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.search("x")
    expected = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert out[0].published_at == expected


def test_search_handles_missing_optional_fields(mast, fake_client):
    """Sparse statuses (no media, no language) must not crash."""
    fake_client.timeline_tag.return_value = [
        {
            "id": "x",
            "content": "<p>body</p>",
            "account": {"id": "u", "username": "u", "acct": "u"},
            "created_at": "2024-01-01T00:00:00.000Z",
            "url": "https://mastodon.social/@u/x",
        }
    ]
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.search("anything")
    c = out[0]
    assert c.source_id == "mastodon:x"
    assert c.thumbnail_url is None
    assert c.published_at is not None


def test_search_extracts_thumbnail_from_first_media(mast, fake_client):
    media = [
        {"preview_url": "https://mastodon.social/preview.jpg", "url": "https://mastodon.social/full.jpg"}
    ]
    fake_client.timeline_tag.return_value = [_status(status_id="m", media=media)]
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.search("x")
    assert out[0].thumbnail_url == "https://mastodon.social/preview.jpg"


# ---------------------------------------------------------------------------
# list_creator_items()
# ---------------------------------------------------------------------------
def test_list_creator_items_resolves_acct_then_lists(mast, fake_client):
    fake_client.lookup_account.return_value = {"id": "42", "acct": "alice@mastodon.social"}
    fake_client.list_account_statuses.return_value = [
        _status(status_id="p1"),
        _status(status_id="p2"),
    ]
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = list(mast.list_creator_items("alice@mastodon.social", limit=7))

    fake_client.lookup_account.assert_called_once_with("alice@mastodon.social")
    fake_client.list_account_statuses.assert_called_once_with("42", limit=7)
    assert [c.source_id for c in out] == ["mastodon:p1", "mastodon:p2"]


def test_list_creator_items_yields_iterator(mast, fake_client):
    """Contract is `Iterable`; today it's a generator — lock that in."""
    fake_client.lookup_account.return_value = {"id": "42", "acct": "alice"}
    fake_client.list_account_statuses.return_value = [_status(status_id="p1")]
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        gen = mast.list_creator_items("alice")
        assert hasattr(gen, "__next__")
        assert next(gen).source_id == "mastodon:p1"


def test_list_creator_items_default_limit_when_none(mast, fake_client):
    fake_client.lookup_account.return_value = {"id": "42", "acct": "alice"}
    fake_client.list_account_statuses.return_value = []
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        list(mast.list_creator_items("alice"))
    fake_client.list_account_statuses.assert_called_once_with("42", limit=25)


def test_list_creator_items_returns_nothing_when_lookup_fails(mast, fake_client):
    """Lookup failures must short-circuit, not crash the orchestrator."""
    fake_client.lookup_account.side_effect = RuntimeError("404")
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = list(mast.list_creator_items("nobody"))
    assert out == []
    fake_client.list_account_statuses.assert_not_called()


def test_list_creator_items_returns_nothing_when_account_id_missing(mast, fake_client):
    fake_client.lookup_account.return_value = {"acct": "alice"}  # no id
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = list(mast.list_creator_items("alice"))
    assert out == []


# ---------------------------------------------------------------------------
# resolve_creator_id()
# ---------------------------------------------------------------------------
def test_resolve_creator_id_strips_at_and_returns_acct(mast, fake_client):
    fake_client.lookup_account.return_value = {"id": "1", "acct": "alice@mastodon.social"}
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        got = mast.resolve_creator_id("@alice@mastodon.social")
    fake_client.lookup_account.assert_called_once_with("alice@mastodon.social")
    assert got == "alice@mastodon.social"


def test_resolve_creator_id_parses_profile_url(mast, fake_client):
    fake_client.lookup_account.return_value = {"id": "1", "acct": "bob@example.org"}
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        got = mast.resolve_creator_id("https://example.org/@bob")
    fake_client.lookup_account.assert_called_once_with("bob@example.org")
    assert got == "bob@example.org"


def test_resolve_creator_id_returns_none_on_lookup_error(mast, fake_client):
    fake_client.lookup_account.side_effect = RuntimeError("404")
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        assert mast.resolve_creator_id("@ghost@mastodon.social") is None


def test_resolve_creator_id_returns_none_on_empty_hint(mast, fake_client):
    """An empty hint shouldn't even reach the network."""
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        assert mast.resolve_creator_id("") is None
    fake_client.lookup_account.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_metadata()
# ---------------------------------------------------------------------------
def test_fetch_metadata_empty_short_circuits(mast, fake_client):
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        assert mast.fetch_metadata([]) == {}
    fake_client.get_status.assert_not_called()


def test_fetch_metadata_calls_get_status_per_id(mast, fake_client):
    """Mastodon has no batch endpoint — connector iterates."""
    fake_client.get_status.side_effect = [
        _status(status_id="111", content="<p>First</p>"),
        _status(status_id="222", content="<p>Second</p>"),
    ]
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.fetch_metadata(["mastodon:111", "mastodon:222"])

    assert fake_client.get_status.call_count == 2
    assert {c.args[0] for c in fake_client.get_status.call_args_list} == {"111", "222"}
    assert set(out.keys()) == {"mastodon:111", "mastodon:222"}
    sm = out["mastodon:111"]
    assert isinstance(sm, SourceMetadata)
    assert sm.creator_external_id == "alice"
    assert sm.extra["favourites_count"] == 5


def test_fetch_metadata_tolerates_unprefixed_ids(mast, fake_client):
    fake_client.get_status.return_value = _status(status_id="999")
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.fetch_metadata(["999"])
    fake_client.get_status.assert_called_once_with("999")
    assert "mastodon:999" in out


def test_fetch_metadata_swallows_per_item_failures(mast, fake_client):
    """One bad id mustn't poison the whole batch."""
    fake_client.get_status.side_effect = [
        RuntimeError("boom"),
        _status(status_id="222"),
    ]
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.fetch_metadata(["mastodon:111", "mastodon:222"])
    assert list(out.keys()) == ["mastodon:222"]


# ---------------------------------------------------------------------------
# fetch_text()
# ---------------------------------------------------------------------------
def _candidate(source_id: str = "mastodon:100") -> Candidate:
    return Candidate(
        source_type="mastodon_post",
        source_id=source_id,
        title="t",
        source_url="https://mastodon.social/@u/100",
    )


def test_fetch_text_returns_extracted_text_on_success(mast, fake_client):
    status = _status(status_id="100", content="<p>Tariff debate</p>", language="en")
    descendants = [
        _status(
            status_id="101",
            content="<p>great point</p>",
            in_reply_to_id="100",
            favourites=10,
        ),
    ]
    fake_client.get_status.return_value = status
    fake_client.get_context.return_value = _context(descendants=descendants)

    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.fetch_text(_candidate("mastodon:100"), job_id="job-7")

    fake_client.get_status.assert_called_once()
    args, _ = fake_client.get_status.call_args
    assert args == ("100",)  # the prefix is stripped
    fake_client.get_context.assert_called_once_with("100")

    assert isinstance(out, ExtractedText)
    assert out.text_source == "mastodon"
    assert out.language == "en"
    assert len(out.segments) == 2  # OP + 1 reply
    assert out.segments[0]["extra"]["kind"] == "status"
    assert out.segments[1]["extra"]["kind"] == "reply"
    # HTML must be stripped from the rendered text.
    assert "<p>" not in out.segments[0]["text"]
    assert "<p>" not in out.segments[1]["text"]
    # Empty query → fail-soft fallback classification populated (D-023).
    assert "classification" in out.extra
    assert out.extra["classification"]["stance"] == "unclear"
    assert out.extra["classification"]["topic_relevance"] == 0.0


def test_fetch_text_calls_classifier_when_query_is_present(mast, fake_client):
    """Per D-023: Mastodon connector calls social_classify inline when
    the orchestrator passes a query. Result lands in
    ExtractedText.extra['classification']."""
    status = _status(status_id="100", content="<p>Caching strategies</p>")
    fake_client.get_status.return_value = status
    fake_client.get_context.return_value = _context()

    fake_classification = {
        "stance": "for",
        "sentiment": "positive",
        "framing": "technical",
        "topic_relevance": 0.85,
    }
    fake_classify_result = Mock()
    fake_classify_result.model_dump.return_value = fake_classification

    with (
        patch.object(
            mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
        ),
        patch(
            "app.sources.mastodon.connector.classify",
            return_value=fake_classify_result,
        ) as mock_classify,
    ):
        out = mast.fetch_text(_candidate("mastodon:100"), job_id="job-7", query="caching")

    assert isinstance(out, ExtractedText)
    mock_classify.assert_called_once()
    call_args = mock_classify.call_args
    assert call_args.args[1] == "caching"
    assert out.extra["classification"] == fake_classification


def test_fetch_text_returns_none_on_get_status_exception(mast, fake_client):
    """Connector must report fetch failures as None, not crash the job."""
    fake_client.get_status.side_effect = RuntimeError("boom")
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        assert mast.fetch_text(_candidate(), job_id="job-1") is None


def test_fetch_text_falls_back_to_op_only_when_context_fails(mast, fake_client):
    """Context failures shouldn't lose the OP — degrade to OP-only."""
    status = _status(status_id="100", content="<p>OP body</p>")
    fake_client.get_status.return_value = status
    fake_client.get_context.side_effect = RuntimeError("503")

    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.fetch_text(_candidate("mastodon:100"))

    assert isinstance(out, ExtractedText)
    assert len(out.segments) == 1
    assert out.segments[0]["extra"]["kind"] == "status"


def test_fetch_text_returns_none_on_empty_segments(mast, fake_client):
    """A status with no body and no replies yields no segments."""
    fake_client.get_status.return_value = _status(content="")
    fake_client.get_context.return_value = _context()
    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        assert mast.fetch_text(_candidate()) is None


def test_fetch_text_uses_status_language_for_extracted_text(mast, fake_client):
    """When Mastodon supplies a language code on the status, surface it
    on the ExtractedText so multilingual indexing knows what it's
    storing."""
    status = _status(status_id="100", content="<p>Hola mundo</p>", language="es")
    fake_client.get_status.return_value = status
    fake_client.get_context.return_value = _context()

    with patch.object(
        mastodon_connector_mod.mastodon_client, "get_client", return_value=fake_client
    ):
        out = mast.fetch_text(_candidate("mastodon:100"))

    assert out is not None
    assert out.language == "es"


# ---------------------------------------------------------------------------
# Flatten module
# ---------------------------------------------------------------------------
def test_flatten_handles_malformed_payload():
    assert mastodon_flatten.flatten_status_with_context([], {}) == ([], {})  # type: ignore[arg-type]
    assert mastodon_flatten.flatten_status_with_context(None, {}) == ([], {})  # type: ignore[arg-type]


def test_flatten_op_only_when_no_descendants():
    status = _status(status_id="1", content="<p>Hello world</p>")
    segments, story_data = mastodon_flatten.flatten_status_with_context(
        status, _context()
    )
    assert story_data["id"] == "1"
    assert len(segments) == 1
    assert "Hello world" in segments[0]["text"]
    assert segments[0]["extra"]["kind"] == "status"
    assert segments[0]["start"] == 0.0
    assert segments[0]["duration"] > 0


def test_flatten_sorts_replies_by_favourites_descending():
    status = _status(status_id="1", content="<p>Question?</p>")
    descendants = [
        _status(status_id="11", content="<p>low</p>", favourites=1, in_reply_to_id="1"),
        _status(status_id="12", content="<p>high</p>", favourites=99, in_reply_to_id="1"),
        _status(status_id="13", content="<p>mid</p>", favourites=10, in_reply_to_id="1"),
    ]
    segments, _ = mastodon_flatten.flatten_status_with_context(
        status, _context(descendants=descendants)
    )
    bodies = [s["text"] for s in segments]
    assert "Question" in bodies[0]
    assert "(favs 99)" in bodies[1]
    assert "(favs 10)" in bodies[2]
    assert "(favs 1)" in bodies[3]


def test_flatten_truncates_to_top_n():
    status = _status(status_id="1", content="<p>q</p>")
    descendants = [
        _status(status_id=str(100 + i), content=f"<p>c{i}</p>", favourites=i, in_reply_to_id="1")
        for i in range(20)
    ]
    segments, _ = mastodon_flatten.flatten_status_with_context(
        status, _context(descendants=descendants), top_n=5
    )
    assert len(segments) == 6  # 1 OP + 5 replies


def test_flatten_renders_depth_markers_for_nested_replies():
    """Replies-of-replies retain `↳ ↳ ` markers so the reader sees
    threading even after favourites-sorting flattens the tree."""
    status = _status(status_id="1", content="<p>q</p>")
    parent = _status(
        status_id="2",
        content="<p>parent</p>",
        favourites=5,
        in_reply_to_id="1",
    )
    child = _status(
        status_id="3",
        content="<p>child</p>",
        favourites=2,
        in_reply_to_id="2",
    )
    segments, _ = mastodon_flatten.flatten_status_with_context(
        status, _context(descendants=[parent, child])
    )
    # The child's marker should be deeper than the parent's.
    reply_segments = [s for s in segments if s["extra"]["kind"] == "reply"]
    parent_seg = next(s for s in reply_segments if s["extra"]["comment_id"] == "2")
    child_seg = next(s for s in reply_segments if s["extra"]["comment_id"] == "3")
    assert parent_seg["extra"]["depth"] == 1
    assert child_seg["extra"]["depth"] == 2
    assert "↳ " in parent_seg["text"]
    assert "↳ ↳ " in child_seg["text"]


def test_flatten_skips_empty_reply_bodies():
    """Empty content (deleted/redacted) replies are dropped."""
    status = _status(status_id="1", content="<p>q</p>")
    descendants = [
        _status(status_id="2", content="", favourites=10, in_reply_to_id="1"),
        _status(status_id="3", content="<p>real</p>", favourites=1, in_reply_to_id="1"),
    ]
    segments, _ = mastodon_flatten.flatten_status_with_context(
        status, _context(descendants=descendants)
    )
    assert len(segments) == 2  # OP + the real reply only


def test_flatten_strips_html_from_bodies():
    """Mastodon delivers status content as HTML (`<p>`, `<a>`, `<br>`).
    We scrub it cheaply so the chunker sees plain prose."""
    status = _status(
        status_id="1",
        content='<p>It&#x27;s &quot;great&quot;</p>',
    )
    descendants = [
        _status(
            status_id="2",
            content='<p>See <a href="https://x.com">link</a></p><p>and more</p>',
            favourites=5,
            in_reply_to_id="1",
        )
    ]
    segments, _ = mastodon_flatten.flatten_status_with_context(
        status, _context(descendants=descendants)
    )
    assert "It's \"great\"" in segments[0]["text"]
    assert "<p>" not in segments[0]["text"]
    assert "See link" in segments[1]["text"]
    assert "and more" in segments[1]["text"]


def test_flatten_segments_have_monotonic_timestamps():
    status = _status(status_id="1", content="<p>body here</p>")
    descendants = [
        _status(status_id="2", content="<p>first reply</p>", favourites=10, in_reply_to_id="1"),
        _status(status_id="3", content="<p>second longer reply text</p>", favourites=5, in_reply_to_id="1"),
    ]
    segments, _ = mastodon_flatten.flatten_status_with_context(
        status, _context(descendants=descendants)
    )
    starts = [s["start"] for s in segments]
    durations = [s["duration"] for s in segments]
    assert starts == sorted(starts)
    assert all(d > 0 for d in durations)


def test_flatten_handles_orphan_reply_without_chain_to_root():
    """If a descendant's `in_reply_to_id` doesn't appear in the
    descendants list (orphan, race), depth defaults to 1 — segment
    still renders."""
    status = _status(status_id="1", content="<p>q</p>")
    orphan = _status(
        status_id="99",
        content="<p>orphan</p>",
        favourites=1,
        in_reply_to_id="ghost-id",  # not in descendants
    )
    segments, _ = mastodon_flatten.flatten_status_with_context(
        status, _context(descendants=[orphan])
    )
    reply_seg = next(s for s in segments if s["extra"]["kind"] == "reply")
    assert reply_seg["extra"]["depth"] == 1


# ---------------------------------------------------------------------------
# Identity / contract sanity
# ---------------------------------------------------------------------------
def test_connector_source_type_is_mastodon_post():
    """Locks the discriminator — changing this would silently break
    every row in `documents` with `source_type='mastodon_post'`."""
    assert MastodonConnector.source_type == "mastodon_post"


def test_connector_registers_under_mastodon_post():
    """Importing the connector module at top of this file should have
    eagerly registered the connector. Verify the registry agrees."""
    from app.sources.mastodon import connector as _  # noqa: F401  re-import is idempotent

    got = registry.connector_for("mastodon_post")
    assert isinstance(got, MastodonConnector)


# ---------------------------------------------------------------------------
# Client: rate-limited GET against the public Mastodon endpoint
# ---------------------------------------------------------------------------
def test_client_get_json_hits_instance_base():
    """Smoke check: `get_json` calls `httpx.get` against the configured
    instance base + `/api/v1<path>` with the expected User-Agent header."""
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = []
    api_resp.raise_for_status = Mock()

    with patch.object(mastodon_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = MastodonClient()
        result = c.get_json("/timelines/tag/foo")

    assert result == []
    assert mock_get.call_count == 1
    called_url = mock_get.call_args.args[0]
    assert "/api/v1/timelines/tag/foo" in called_url
    headers = mock_get.call_args.kwargs["headers"]
    assert "User-Agent" in headers


def test_client_get_json_raises_on_http_error():
    """Non-2xx surfaces as `httpx.HTTPError` — there's no auth retry path
    because the endpoint is unauthenticated."""
    import httpx as _httpx

    bad_resp = Mock(status_code=500)
    bad_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
        "500", request=Mock(), response=bad_resp
    )

    with patch.object(mastodon_client_mod.httpx, "get", return_value=bad_resp):
        c = MastodonClient()
        with pytest.raises(_httpx.HTTPStatusError):
            c.get_json("/timelines/tag/foo")


def test_client_timeline_tag_clamps_limit_to_40():
    """Mastodon caps `limit` at 40; client clamps defensively rather
    than letting the instance reject the request."""
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = []
    api_resp.raise_for_status = Mock()

    with patch.object(mastodon_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = MastodonClient()
        c.timeline_tag("rust", limit=100)

    params = mock_get.call_args.kwargs["params"]
    assert params == {"limit": 40}


def test_client_timeline_tag_passes_user_supplied_limit_under_40():
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = []
    api_resp.raise_for_status = Mock()

    with patch.object(mastodon_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = MastodonClient()
        c.timeline_tag("rust", limit=15)

    params = mock_get.call_args.kwargs["params"]
    assert params == {"limit": 15}


def test_client_get_status_hits_correct_path():
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"id": "x"}
    api_resp.raise_for_status = Mock()

    with patch.object(mastodon_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = MastodonClient()
        c.get_status("123")

    called_url = mock_get.call_args.args[0]
    assert called_url.endswith("/statuses/123")


def test_client_get_context_hits_correct_path():
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"ancestors": [], "descendants": []}
    api_resp.raise_for_status = Mock()

    with patch.object(mastodon_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = MastodonClient()
        c.get_context("123")

    called_url = mock_get.call_args.args[0]
    assert called_url.endswith("/statuses/123/context")


def test_client_lookup_account_passes_acct_param():
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"id": "1", "acct": "alice"}
    api_resp.raise_for_status = Mock()

    with patch.object(mastodon_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = MastodonClient()
        c.lookup_account("alice@mastodon.social")

    params = mock_get.call_args.kwargs["params"]
    assert params == {"acct": "alice@mastodon.social"}


def test_client_list_account_statuses_excludes_reblogs():
    """Reblogs would inflate the creator-feed candidate count without
    adding new authored content — we exclude them."""
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = []
    api_resp.raise_for_status = Mock()

    with patch.object(mastodon_client_mod.httpx, "get", return_value=api_resp) as mock_get:
        c = MastodonClient()
        c.list_account_statuses("42", limit=10)

    params = mock_get.call_args.kwargs["params"]
    assert params == {"limit": 10, "exclude_reblogs": "true"}
