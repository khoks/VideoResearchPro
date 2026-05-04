"""Tests for the BYOK Twitter connector + bearer-auth client.

Strategy mirrors the article connector tests (PR #145): mock the
client + httpx so we lock down shape transformation (Twitter v2 JSON
→ Candidates) and wiring (which endpoint each method calls). No
network calls; no real bearer tokens.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import httpx
import pytest

from app.sources import registry
from app.sources.twitter import client as twitter_client_mod
from app.sources.twitter import connector as twitter_connector_mod
from app.sources.twitter.client import TwitterClient
from app.sources.twitter.connector import TwitterConnector
from app.sources.types import Candidate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def twitter_conn():
    return TwitterConnector()


@pytest.fixture
def fake_client():
    return Mock(spec=TwitterClient)


def _tweet(
    tweet_id: str = "100",
    text: str = "A sample tweet",
    author_id: str = "u1",
    created_at: str = "2024-01-15T12:00:00.000Z",
    like_count: int = 50,
    retweet_count: int = 10,
    reply_count: int = 5,
) -> dict:
    return {
        "id": tweet_id,
        "text": text,
        "author_id": author_id,
        "created_at": created_at,
        "public_metrics": {
            "like_count": like_count,
            "retweet_count": retweet_count,
            "reply_count": reply_count,
            "quote_count": 0,
            "impression_count": 1000,
        },
        "lang": "en",
    }


def _user(user_id: str = "u1", username: str = "alice", name: str = "Alice") -> dict:
    return {"id": user_id, "username": username, "name": name, "verified": False}


def _search_payload(*tweets: dict, users: list[dict] | None = None) -> dict:
    return {
        "data": list(tweets),
        "includes": {"users": users or [_user()]},
        "meta": {"result_count": len(tweets)},
    }


# ---------------------------------------------------------------------------
# Identity / re-registration
# ---------------------------------------------------------------------------


def test_twitter_connector_re_registers_under_tweet():
    """Importing this module should overwrite the paste-only
    TweetConnector from app.sources.paste_url. Verify the registry
    resolves to the search-having class."""
    from app.sources.twitter import connector as _  # noqa: F401

    got = registry.connector_for("tweet")
    assert got.__class__.__name__ == "TwitterConnector"
    assert got.__class__.__module__ == "app.sources.twitter.connector"


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------


def test_search_returns_empty_when_query_blank(twitter_conn, fake_client):
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        assert twitter_conn.search("   ") == []
    fake_client.search_recent.assert_not_called()


def test_search_returns_empty_when_token_unset(twitter_conn, fake_client, monkeypatch):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", ""
    )
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        out = twitter_conn.search("anything")
    assert out == []
    fake_client.search_recent.assert_not_called()


def test_search_returns_candidates_with_resolved_users(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "fake-token"
    )
    fake_client.search_recent.return_value = _search_payload(
        _tweet(tweet_id="100", text="First tweet", author_id="u1"),
        _tweet(tweet_id="101", text="Second tweet", author_id="u1"),
        users=[_user()],
    )
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        out = twitter_conn.search("rust", limit=5)
    fake_client.search_recent.assert_called_once_with("rust", limit=5)
    assert len(out) == 2
    assert all(isinstance(c, Candidate) for c in out)
    assert all(c.source_type == "tweet" for c in out)
    # User expansion resolved → username 'alice' shows up in source_url + creator_name.
    assert all(c.source_url.startswith("https://x.com/alice/status/") for c in out)
    assert all(c.creator_name == "Alice" for c in out)
    assert all(c.creator_external_id == "alice" for c in out)


def test_search_handles_missing_user_expansion(
    twitter_conn, fake_client, monkeypatch
):
    """If `includes.users` is missing or doesn't contain the
    author_id, fall back to a numeric-id-only URL."""
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "fake-token"
    )
    fake_client.search_recent.return_value = {
        "data": [_tweet(tweet_id="999", author_id="u_unknown")],
        "includes": {"users": []},
        "meta": {"result_count": 1},
    }
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        out = twitter_conn.search("x")
    # Falls through to /i/status/ canonical when handle isn't resolvable.
    assert out[0].source_url == "https://x.com/i/status/999"
    assert out[0].creator_name is None


def test_search_carries_public_metrics_in_extra(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.search_recent.return_value = _search_payload(
        _tweet(like_count=999, retweet_count=42, reply_count=7),
        users=[_user()],
    )
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        out = twitter_conn.search("x")
    assert out[0].extra["like_count"] == 999
    assert out[0].extra["retweet_count"] == 42
    assert out[0].extra["reply_count"] == 7


def test_search_returns_empty_on_api_error(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.search_recent.side_effect = httpx.ConnectError("DNS")
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        out = twitter_conn.search("anything")
    assert out == []


def test_search_caps_at_limit(twitter_conn, fake_client, monkeypatch):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.search_recent.return_value = _search_payload(
        *(_tweet(tweet_id=str(100 + i)) for i in range(20)),
        users=[_user()],
    )
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        out = twitter_conn.search("x", limit=5)
    assert len(out) == 5


# ---------------------------------------------------------------------------
# list_creator_items()
# ---------------------------------------------------------------------------


def test_list_creator_items_resolves_handle_then_lists(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.get_user_by_username.return_value = {
        "data": _user(user_id="42", username="alice")
    }
    fake_client.get_user_tweets.return_value = {
        "data": [
            _tweet(tweet_id="500", text="A"),
            _tweet(tweet_id="501", text="B"),
        ]
    }
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        out = list(twitter_conn.list_creator_items("alice", limit=10))

    fake_client.get_user_by_username.assert_called_once_with("alice")
    fake_client.get_user_tweets.assert_called_once_with("42", limit=10)
    assert [c.source_id for c in out] == ["tweet:500", "tweet:501"]
    # All candidates are linked to the resolved username.
    assert all("alice/status" in c.source_url for c in out)


def test_list_creator_items_passes_through_numeric_user_id(
    twitter_conn, fake_client, monkeypatch
):
    """Numeric IDs skip the username-lookup roundtrip."""
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.get_user_tweets.return_value = {
        "data": [_tweet(tweet_id="700")]
    }
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        out = list(twitter_conn.list_creator_items("123456789"))

    fake_client.get_user_by_username.assert_not_called()
    fake_client.get_user_tweets.assert_called_once_with("123456789", limit=25)
    assert len(out) == 1


def test_list_creator_items_strips_at_prefix(twitter_conn, fake_client, monkeypatch):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.get_user_by_username.return_value = {
        "data": _user(user_id="9", username="alice")
    }
    fake_client.get_user_tweets.return_value = {"data": []}
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        list(twitter_conn.list_creator_items("@alice"))
    fake_client.get_user_by_username.assert_called_once_with("alice")


def test_list_creator_items_returns_nothing_when_token_unset(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", ""
    )
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        out = list(twitter_conn.list_creator_items("alice"))
    assert out == []
    fake_client.get_user_by_username.assert_not_called()


def test_list_creator_items_returns_nothing_on_user_lookup_failure(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.get_user_by_username.side_effect = httpx.ConnectError("DNS")
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        out = list(twitter_conn.list_creator_items("alice"))
    assert out == []
    fake_client.get_user_tweets.assert_not_called()


def test_list_creator_items_returns_nothing_when_tweet_listing_fails(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.get_user_by_username.return_value = {
        "data": _user(user_id="42", username="alice")
    }
    fake_client.get_user_tweets.side_effect = httpx.HTTPStatusError(
        "rate limited", request=Mock(), response=Mock(status_code=429)
    )
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        out = list(twitter_conn.list_creator_items("alice"))
    assert out == []


# ---------------------------------------------------------------------------
# resolve_creator_id()
# ---------------------------------------------------------------------------


def test_resolve_creator_id_passes_through_numeric_user_id(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        got = twitter_conn.resolve_creator_id("123456789")
    assert got == "123456789"
    fake_client.get_user_by_username.assert_not_called()


def test_resolve_creator_id_resolves_handle(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.get_user_by_username.return_value = {
        "data": _user(username="alice")
    }
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        got = twitter_conn.resolve_creator_id("@alice")
    fake_client.get_user_by_username.assert_called_once_with("alice")
    assert got == "alice"


def test_resolve_creator_id_parses_x_com_url(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.get_user_by_username.return_value = {
        "data": _user(username="alice")
    }
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        got = twitter_conn.resolve_creator_id("https://x.com/alice")
    fake_client.get_user_by_username.assert_called_once_with("alice")
    assert got == "alice"


def test_resolve_creator_id_parses_twitter_com_url(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.get_user_by_username.return_value = {
        "data": _user(username="bob")
    }
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        got = twitter_conn.resolve_creator_id("https://twitter.com/bob")
    assert got == "bob"


def test_resolve_creator_id_returns_none_when_token_unset(
    twitter_conn, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", ""
    )
    assert twitter_conn.resolve_creator_id("@alice") is None


def test_resolve_creator_id_returns_none_on_lookup_failure(
    twitter_conn, fake_client, monkeypatch
):
    monkeypatch.setattr(
        twitter_connector_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    fake_client.get_user_by_username.side_effect = RuntimeError("404")
    with patch.object(
        twitter_connector_mod.twitter_client,
        "get_client",
        return_value=fake_client,
    ):
        assert twitter_conn.resolve_creator_id("@ghost") is None


# ---------------------------------------------------------------------------
# Client: bearer-auth + rate-limit smoke
# ---------------------------------------------------------------------------


def test_client_get_json_raises_when_no_bearer(monkeypatch):
    monkeypatch.setattr(
        twitter_client_mod.settings, "TWITTER_BEARER_TOKEN", ""
    )
    c = TwitterClient()
    with pytest.raises(RuntimeError):
        c.get_json("/tweets/1")


def test_client_get_json_sends_bearer_auth_header(monkeypatch):
    monkeypatch.setattr(
        twitter_client_mod.settings, "TWITTER_BEARER_TOKEN", "secret-bearer"
    )
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"data": []}
    api_resp.raise_for_status = Mock()

    with patch.object(
        twitter_client_mod.httpx, "get", return_value=api_resp
    ) as mock_get:
        c = TwitterClient()
        c.get_json("/tweets/search/recent", params={"query": "x"})

    headers = mock_get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret-bearer"
    assert "User-Agent" in headers
    called_url = mock_get.call_args.args[0]
    assert called_url.endswith("/tweets/search/recent")


def test_client_search_recent_sets_expected_params(monkeypatch):
    monkeypatch.setattr(
        twitter_client_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"data": [], "includes": {"users": []}}
    api_resp.raise_for_status = Mock()
    with patch.object(
        twitter_client_mod.httpx, "get", return_value=api_resp
    ) as mock_get:
        c = TwitterClient()
        c.search_recent("rust async", limit=15)

    params = mock_get.call_args.kwargs["params"]
    assert params["query"] == "rust async"
    # Floor at 10 because v2 free tier minimum is 10.
    assert params["max_results"] >= 10
    assert "tweet.fields" in params
    assert params["expansions"] == "author_id"


def test_client_search_recent_clamps_limit_to_100(monkeypatch):
    monkeypatch.setattr(
        twitter_client_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"data": []}
    api_resp.raise_for_status = Mock()
    with patch.object(
        twitter_client_mod.httpx, "get", return_value=api_resp
    ) as mock_get:
        c = TwitterClient()
        c.search_recent("x", limit=999)
    assert mock_get.call_args.kwargs["params"]["max_results"] == 100


def test_client_get_user_by_username_path():
    """Smoke check — the path component contains the username."""
    monkeypatch_token = patch.object(
        twitter_client_mod.settings, "TWITTER_BEARER_TOKEN", "k"
    )
    api_resp = Mock(status_code=200)
    api_resp.json.return_value = {"data": {"username": "alice"}}
    api_resp.raise_for_status = Mock()
    with monkeypatch_token, patch.object(
        twitter_client_mod.httpx, "get", return_value=api_resp
    ) as mock_get:
        c = TwitterClient()
        c.get_user_by_username("alice")
    assert mock_get.call_args.args[0].endswith("/users/by/username/alice")


def test_client_is_enabled_reflects_token_presence(monkeypatch):
    monkeypatch.setattr(
        twitter_client_mod.settings, "TWITTER_BEARER_TOKEN", ""
    )
    assert TwitterClient.is_enabled() is False
    monkeypatch.setattr(
        twitter_client_mod.settings, "TWITTER_BEARER_TOKEN", "anything"
    )
    assert TwitterClient.is_enabled() is True
