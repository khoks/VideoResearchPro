"""T-4.11.4.2 at each changed call site: a line the worker writes names no
user's words, no address and no account, and still says what happened.

Each test patches the module's logger and reads every call's arguments, so a
word that reached a line in its format string or as an argument is caught.
A patched logger proves the call; ``tests/test_tasks/test_worker_log_words.py``
runs a topic job's search phase and reads what a real handler wrote.
"""
from __future__ import annotations

import json
import smtplib
from datetime import datetime
from unittest.mock import MagicMock, patch

import httplib2
import httpx
import pytest
from googleapiclient.errors import HttpError

from app.agents import qa_agent, search_agent
from app.config import settings
from app.connectors import registry as echo_registry
from app.connectors.base import ConnectorTokens
from app.connectors.github import connector as github_connector
from app.connectors.github.connector import GitHubConnector, HttpResponse
from app.models.echo_connector import EchoConnectorGrant
from app.services import connector_dispatch, email_service, quota_service, youtube_service
from app.services import echo_connector_service as echo_svc
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.mastodon import client as mastodon_client
from app.sources.mastodon import connector as mastodon_connector

TOPIC = "Zanzibar quokka fermentation"
LINK = "https://www.youtube.com/@stoatlab?si=SHAREtoken123"
NAME = "Wombat Brewing Society"
FORBIDDEN = ("zanzibar", "quokka", "fermentation", "sharetoken123", "wombat")


def said(logger: MagicMock) -> str:
    """Everything the patched logger was given, lower-cased: each line as the
    handler would render it, then every argument and keyword on its own."""
    parts = []
    for call in logger.method_calls:
        args = call.args
        if args:
            try:
                parts.append(str(args[0]) % tuple(args[1:]) if len(args) > 1 else str(args[0]))
            except (TypeError, ValueError):
                pass
        parts.extend(str(a) for a in args)
        parts.extend(f"{k}={v}" for k, v in call.kwargs.items())
    return "\n".join(parts).lower()


def assert_no_words(logger: MagicMock, *also: str) -> str:
    text = said(logger)
    assert text, "nothing was logged, so nothing was checked"
    for word in (*FORBIDDEN, *also):
        assert word.lower() not in text, f"{word!r} reached a log line:\n{text}"
    return text


def http_error(params: dict, status: int = 400, reason: str = "badRequest") -> HttpError:
    """An HttpError as googleapiclient builds one: its text quotes the URI."""
    from urllib.parse import urlencode

    uri = "https://youtube.googleapis.com/youtube/v3/search?" + urlencode({**params, "key": "AIzaSyFAKEFAKEFAKE00"})
    body = json.dumps({"error": {"message": "Bad Request", "errors": [{"reason": reason, "message": "x"}]}})
    return HttpError(httplib2.Response({"status": status}), body.encode(), uri=uri)


class FakeYouTube:
    """``get_youtube_client()``: a handle lookup finds nothing, and a search
    answers ``search_items`` or raises an HttpError quoting its ``q``."""

    def __init__(self, search_items: list | None = None):
        self.search_items = search_items
        self.queries: list[str] = []

    def channels(self):
        class _Channels:
            def list(self, **params):
                return MagicMock(execute=MagicMock(return_value={"items": []}))

        return _Channels()

    def search(self):
        outer = self

        class _Search:
            def list(self, **params):
                outer.queries.append(params["q"])

                def execute():
                    if outer.search_items is None:
                        raise http_error(params)
                    return {"items": outer.search_items}

                return MagicMock(execute=execute)

        return _Search()


@pytest.fixture
def youtube(monkeypatch):
    fake = FakeYouTube()
    monkeypatch.setattr(youtube_service, "get_youtube_client", lambda: fake)
    monkeypatch.setattr(quota_service, "record", lambda *a, **kw: None)
    return fake


@pytest.fixture
def yt_log(monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(youtube_service, "logger", log)
    return log


# ---------------------------------------------------------------------------
# youtube_service
# ---------------------------------------------------------------------------

def test_search_videos_logs_the_querys_length_and_the_results(youtube, yt_log):
    youtube.search_items = []
    youtube_service.search_videos(f"{TOPIC} history", max_results=5)

    text = assert_no_words(yt_log)
    assert f"query of {len(TOPIC) + 8} characters" in text
    assert "returned 0 results" in text


def test_a_failed_search_logs_the_status_and_reason_not_the_request(youtube, yt_log):
    with pytest.raises(HttpError):
        youtube_service.search_videos(TOPIC)

    text = assert_no_words(yt_log, "googleapis", "aiza")
    assert "youtube api search failed: httperror 400 (badrequest)" in text


def test_a_quota_refusal_logs_the_status_and_reason_not_the_request(youtube, yt_log):
    def refuse(**params):
        raise http_error(params, status=403, reason="quotaExceeded")

    youtube.search = lambda: MagicMock(list=lambda **p: MagicMock(execute=lambda: refuse(**p)))
    with pytest.raises(youtube_service.QuotaExceededError):
        youtube_service.search_videos(TOPIC)

    text = assert_no_words(yt_log, "googleapis")
    assert "quota exceeded on operation=search: httperror 403 (quotaexceeded)" in text


@pytest.mark.parametrize("channel_input, kind", [
    (LINK, "a link on www.youtube.com"),
    (NAME, "a name of 22 characters"),
    ("@Wombat Brewing Society", "a name of 23 characters"),
])
def test_resolving_a_channel_names_the_inputs_kind(youtube, yt_log, channel_input, kind):
    youtube.search_items = []
    assert youtube_service.resolve_channel_id(channel_input, job_id="job-1") is None

    text = assert_no_words(yt_log)
    assert f"input is {kind}" in text
    assert f"could not resolve {kind}" in text
    assert youtube.queries == [channel_input], "the search itself still asks for what the user typed"


def test_a_name_shaped_like_a_channel_id_is_still_a_name(youtube, yt_log):
    """24 characters starting with "UC" used to count as an id: the line wrote
    the name, and the name came back as if it were an id."""
    name = "UC Berkeley Data Science"
    assert len(name) == 24
    youtube.search_items = [{"snippet": {"channelId": "UCabcdefghijklmnopqrstuv"}}]

    assert youtube_service.resolve_channel_id(name, job_id="job-1") == "UCabcdefghijklmnopqrstuv"

    text = assert_no_words(yt_log, "berkeley", "science")
    assert "input is a name of 24 characters" in text
    assert "direct channel id detected" not in text
    assert youtube.queries == [name], "the name goes to the search, as a name does"


def test_what_follows_channel_in_a_link_is_named_by_kind(youtube, yt_log):
    link = "https://www.youtube.com/channel/UC wombat brewing society/videos"
    assert youtube_service.resolve_channel_id(link) == "UC wombat brewing society"

    text = assert_no_words(yt_log)
    assert "extracted from url → a name of 25 characters" in text


def test_a_channel_id_and_its_link_stand_as_written(youtube, yt_log):
    cid = "UCabcdefghijklmnopqrstuv"
    assert youtube_service.resolve_channel_id(cid) == cid
    assert youtube_service.resolve_channel_id(f"https://www.youtube.com/channel/{cid}?si=SHAREtoken123") == cid

    text = assert_no_words(yt_log)
    assert f"direct channel id detected → {cid.lower()}" in text
    assert f"extracted from url → {cid.lower()}" in text
    assert youtube.queries == [], "an id costs no search"


def test_a_handle_is_the_channels_public_name_and_stands(youtube, yt_log):
    youtube.search_items = [{"snippet": {"channelId": "UCabcdefghijklmnopqrstuv"}}]
    youtube_service.resolve_channel_id(LINK)

    text = assert_no_words(yt_log)
    assert "resolving handle @stoatlab via api" in text
    assert "search fallback → ucabcdefghijklmnopqrstuv" in text


# ---------------------------------------------------------------------------
# search_agent
# ---------------------------------------------------------------------------

def test_preferred_channel_hints_are_named_by_kind(youtube, monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(search_agent, "logger", log)
    monkeypatch.setattr(youtube_service, "logger", MagicMock())

    out = search_agent.resolve_preferred_channels({"preferred_channels": [LINK, NAME]})

    assert out["preferred_channel_ids"] == []
    assert out["unresolved_channels"] == [LINK, NAME], "the run still reports what the user typed"
    text = assert_no_words(log, "googleapis")
    assert "a link on www.youtube.com raised, skipping" in text
    assert "a name of 22 characters raised, skipping" in text
    assert "googleapiclient.errors.httperror" in text, "the type and the frames stay"
    assert "resolve_channel_id" in text


def test_a_hint_that_finds_no_channel_is_named_by_kind(youtube, monkeypatch):
    youtube.search_items = []
    log = MagicMock()
    monkeypatch.setattr(search_agent, "logger", log)
    monkeypatch.setattr(youtube_service, "logger", MagicMock())

    out = search_agent.resolve_preferred_channels({"preferred_channels": [LINK, NAME]})

    assert out["unresolved_channels"] == [LINK, NAME]
    text = assert_no_words(log)
    assert "could not resolve a link on www.youtube.com" in text
    assert "could not resolve a name of 22 characters" in text


def test_a_failed_broad_search_names_the_query_by_its_place(youtube, monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(search_agent, "logger", log)
    monkeypatch.setattr(youtube_service, "logger", MagicMock())

    videos, failure = search_agent._run_broad_searches([f"{TOPIC} history", f"{TOPIC} today"], target=5)

    assert videos == {} and isinstance(failure, HttpError)
    text = assert_no_words(log, "googleapis")
    assert "broad search 1 of 2 failed" in text and "broad search 2 of 2 failed" in text
    assert "googleapiclient.errors.httperror" in text


# ---------------------------------------------------------------------------
# connector_dispatch
# ---------------------------------------------------------------------------

class _Raising(BaseConnector):
    source_type = "hn_story"

    def search(self, query, instructions="", limit=10):
        request = httpx.Request("GET", f"https://hn.algolia.com/api/v1/search?query={query}")
        httpx.Response(503, request=request).raise_for_status()

    def list_creator_items(self, *a, **kw):  # pragma: no cover
        return []

    def fetch_metadata(self, *a, **kw):  # pragma: no cover
        return {}

    def fetch_text(self, *a, **kw):  # pragma: no cover
        return None


def test_a_connectors_search_failure_logs_the_type_status_and_frames(monkeypatch):
    snapshot = registry.all_connectors()
    registry._reset_for_tests()
    registry.register(_Raising())
    log = MagicMock()
    monkeypatch.setattr(connector_dispatch, "logger", log)
    try:
        result = connector_dispatch.dispatch_search(["hn_story"], query=TOPIC, job_id="job-7")
    finally:
        registry._reset_for_tests()
        for connector in snapshot.values():
            registry.register(connector)

    assert result.errors_by_source_type == {"hn_story": "HTTPStatusError"}
    assert result.failures_by_source_type["hn_story"].status == 503
    text = assert_no_words(log, "algolia")
    assert "connector 'hn_story' raised during search() (failed, http 503)" in text
    assert "httpx.httpstatuserror" in text


# ---------------------------------------------------------------------------
# Mastodon
# ---------------------------------------------------------------------------

def test_mastodon_names_an_empty_query_by_its_length(monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(mastodon_connector, "logger", log)

    assert mastodon_connector.MastodonConnector().search("!!! ??? ...") == []

    text = said(log)
    assert "a query of 11 characters normalised to no hashtag" in text
    assert "!!!" not in text


def test_mastodon_names_a_failed_hashtag_by_its_length(monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(mastodon_connector, "logger", log)
    calls: list[str] = []

    class _Client:
        def timeline_tag(self, tag, limit=25):
            calls.append(tag)
            if len(calls) == 1:
                return [{"id": "1", "content": "<p>hi</p>", "account": {"acct": "a"}, "url": "https://m.example/1"}]
            request = httpx.Request("GET", f"https://mastodon.social/api/v1/timelines/tag/{tag}")
            httpx.Response(500, request=request).raise_for_status()

    monkeypatch.setattr(mastodon_client, "get_client", lambda: _Client())

    mastodon_connector.MastodonConnector().search(TOPIC, limit=10)

    assert len(calls) >= 2, "a second hashtag was tried and failed"
    text = assert_no_words(log, "mastodon.social")
    assert "search failed for a hashtag of" in text and "httpstatuserror" in text


# ---------------------------------------------------------------------------
# email
# ---------------------------------------------------------------------------

def test_a_failed_smtp_delivery_names_no_recipient_or_subject(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_USE_STARTTLS", False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", None)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
    log = MagicMock()
    monkeypatch.setattr(email_service, "logger", log)
    fake_smtp = MagicMock()
    fake_smtp.__enter__.return_value = fake_smtp
    fake_smtp.__exit__.return_value = False
    # smtplib's refusal quotes the recipient.
    fake_smtp.send_message.side_effect = smtplib.SMTPRecipientsRefused(
        {"wombat.reader@example.com": (550, b"no such user")}
    )

    with patch("app.services.email_service.smtplib.SMTP", return_value=fake_smtp):
        ok = email_service.send_email("wombat.reader@example.com", f"New answer: {TOPIC}", "Body")

    assert ok is False
    failure = [c for c in log.method_calls if c[0] == "error"]
    assert len(failure) == 1
    text = " ".join(str(a) for a in failure[0].args).lower()
    assert "smtp delivery failed" in text and "smtprecipientsrefused" in text
    assert "wombat" not in text and "zanzibar" not in text and "example.com" not in text
    # The fallback still writes the email whole for the operator (OQ-44).
    fallback = [c for c in log.method_calls if c[0] == "info"]
    assert fallback and "wombat.reader@example.com" in [str(a) for a in fallback[0].args]


# ---------------------------------------------------------------------------
# Echo's GitHub connector, through the sync runtime
# ---------------------------------------------------------------------------

def test_a_failed_github_sync_names_the_endpoint_not_the_account(db, monkeypatch):
    def request(method, url, *, headers, data=None, json=None, auth=None):
        return HttpResponse(500, {"message": "boom"})

    connector = GitHubConnector(request=request)
    connector.name = "github_words"
    echo_registry.register_connector(connector)
    log = MagicMock()
    monkeypatch.setattr(echo_svc, "logger", log)
    tenant = "22222222-2222-2222-2222-222222222222"
    try:
        echo_svc._store_tokens(db, tenant, connector.name, ConnectorTokens(access_token="gh", account_label="wombat-login"))
        grant = EchoConnectorGrant(tenant_id=tenant, connector=connector.name, consent_version="v",
                                   backfilled_at=datetime(2020, 1, 1), account_label="wombat-login")
        db.add(grant)
        db.commit()
        outcome = echo_svc.run_sync(db, grant.id)
    finally:
        echo_registry.unregister_connector(connector.name)

    assert outcome.status == "error"
    text = assert_no_words(log)
    assert "github answered 500 for /users/{login}/events" in text
    db.expire_all()
    assert db.get(EchoConnectorGrant, grant.id).last_error.endswith("for /users/{login}/events")


def test_a_skipped_repository_is_not_named(monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(github_connector, "logger", log)
    from app.connectors.base import SyncContext

    def request(method, url, *, headers, data=None, json=None, auth=None):
        return HttpResponse(409, {"message": "Git Repository is empty."})

    ctx = SyncContext(tenant_id="t", tokens=ConnectorTokens(access_token="gh", account_label="wombat-login"), cursor={})
    events = list(GitHubConnector(request=request)._commits(ctx, "wombat-login", "wombat-login/zanzibar", since=None))

    assert events == []
    text = assert_no_words(log)
    assert "skipping one repository's commits: github answered 409 for /repos/{repo}/commits" in text


def test_a_github_request_writes_no_httpx_line(monkeypatch):
    """The sync's URLs name the login and its repositories."""
    import io
    import logging

    real_client = httpx.Client
    monkeypatch.setattr(
        github_connector.httpx, "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])), **kw),
    )
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        github_connector._default_request("GET", "https://api.github.com/users/wombat-login/events", headers={})
        with real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as control:
            control.get("https://example.com/control")
    finally:
        root.removeHandler(handler)
        root.setLevel(level)

    written = stream.getvalue()
    assert "https://example.com/control" in written, "the handler does see httpx's line"
    assert "wombat" not in written


# ---------------------------------------------------------------------------
# DEBUG's statement echo (part 2): documented, not changed
# ---------------------------------------------------------------------------

def test_debug_echo_writes_each_statements_values_and_nothing_else_follows_debug():
    """What CLAUDE.md's DEBUG row and .env.example say: the echo writes each
    statement with its bound values. The setting's behaviour is unchanged:
    the app's engine follows DEBUG with ``echo`` alone, and a database error's
    text keeps its values with DEBUG off as before (hiding them is the owner's
    call, not this item's)."""
    import io
    import logging

    from sqlalchemy import create_engine, text

    from app import database

    assert database.engine.echo == settings.DEBUG
    assert database.engine.hide_parameters is False

    # Echo would add a stdout handler to SQLAlchemy's logger for the rest of
    # the session; the engine logger at INFO is what echo turns on, and it
    # writes the same lines to a handler of the test's own.
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    engine_log = logging.getLogger("sqlalchemy.engine.Engine")
    level = engine_log.level
    engine_log.addHandler(handler)
    engine_log.setLevel(logging.INFO)
    try:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        with engine.connect() as conn:
            conn.execute(text("select :q"), {"q": f"How does {TOPIC} work?"})
    finally:
        engine_log.removeHandler(handler)
        engine_log.setLevel(level)

    assert TOPIC in stream.getvalue(), "the echo writes the bound value, as the docs now say"


# ---------------------------------------------------------------------------
# social_classify_stance, whose prompt holds the run's topic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reply, line", [
    (f"I think this post is skeptical of {TOPIC} claims.", "returned non-json of"),
    (json.dumps([f"{TOPIC}", "for"]), "returned a json list, not an object"),
    (json.dumps({"stance": "for", "sentiment": "mixed", "framing": f"skeptical of {TOPIC} claims",
                 "topic_relevance": 0.9, f"{TOPIC}": "yes"}),
     "schema validation failed (validationerror on framing)"),
])
def test_a_classifier_reply_that_fails_is_logged_without_its_words(monkeypatch, reply, line):
    from app.services import llm_service, social_classify

    log = MagicMock()
    monkeypatch.setattr(social_classify, "logger", log)
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=reply)
    monkeypatch.setattr(llm_service, "get_llm_for", lambda *a, **kw: llm)

    out = social_classify.classify("A post about cloves on the island.", TOPIC)

    assert out.stance == "unclear", "the fallback still applies"
    assert TOPIC in llm.invoke.call_args.args[0][1].content, "the prompt did carry the topic"
    text = assert_no_words(log, "skeptical")
    assert line in text


# ---------------------------------------------------------------------------
# Library Q&A, which a saved search runs in the worker
# ---------------------------------------------------------------------------

def test_a_used_sources_reply_that_is_not_json_is_logged_by_length(monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(qa_agent, "logger", log)
    rag = [{
        "text": "Fermentation in Zanzibar uses cloves.",
        "metadata": {"video_id": "vZ", "video_title": "Spice Island Kitchens", "channel_name": "Cooks",
                     "video_url": "https://www.youtube.com/watch?v=vZ", "timestamp_start": 0.0},
        "distance": 0.1,
    }]

    def llm(payload):
        fake = MagicMock()
        fake.invoke.return_value = MagicMock(content=payload)
        return fake

    llms = [
        llm(""),  # sub-queries
        llm("Cloves."),  # refine
        llm("Quokka fermentation in Zanzibar relies on cloves."),  # answer, no citation
        llm("The answer about quokka fermentation in Zanzibar used the first source."),  # used sources
    ]
    with patch.object(qa_agent.chroma_service, "query_collection", return_value=rag), \
         patch.object(qa_agent, "get_llm_for", side_effect=llms):
        qa_agent.run_library_qa_agent(question=f"How does {TOPIC} work?")

    text = assert_no_words(log)
    assert "used-sources llm returned non-json content of" in text
