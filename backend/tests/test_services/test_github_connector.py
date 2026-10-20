"""S-3.2.4 — the GitHub connector against recorded-shape fixtures.

Synthetic responses in GitHub's REST shapes (no real account): the events
feed (pushes carry no commit list since GitHub's 2025-08 change), the user's
repositories, and the commits they authored. The connector maps what Echo
keeps, keeps text only where the user wrote it, walks commits with
``author=<login>``, derives language skills below the user's own word, and
treats 401 as "reconnect".
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone

import pytest

from app.config import settings
from app.connectors import registry
from app.connectors.base import ActivityConnector, ConnectorError, ConnectorTokens, SyncContext
from app.connectors.github.connector import GitHubConnector, HttpResponse

LOGIN = "octo-test"


def _event(eid, kind, repo, created, payload=None, actor=LOGIN):
    return {"id": str(eid), "type": kind, "actor": {"login": actor}, "repo": {"name": repo},
            "payload": payload or {}, "created_at": created}


EVENTS = [
    _event(300, "PushEvent", f"{LOGIN}/parser", "2026-10-18T10:00:00Z",
           {"ref": "refs/heads/main", "head": "abc300", "before": "abc299"}),
    _event(299, "PullRequestEvent", f"{LOGIN}/parser", "2026-10-17T10:00:00Z",
           {"action": "opened", "number": 7, "pull_request": {"number": 7, "title": "Stream the tokenizer",
                                                              "body": "Reads in chunks so big files fit.", "html_url": "https://github.com/x/7"}}),
    _event(298, "PullRequestEvent", f"{LOGIN}/parser", "2026-10-16T10:00:00Z",
           {"action": "closed", "pull_request": {"number": 6, "title": "Old", "merged": True}}),
    _event(297, "IssueCommentEvent", "someone/lib", "2026-10-15T10:00:00Z",
           {"action": "created", "issue": {"title": "Crash on empty input"}, "comment": {"body": "Same here; a guard fixes it."}}),
    _event(296, "WatchEvent", "someone/lib", "2026-10-14T10:00:00Z", {"action": "started"}),
    _event(295, "CreateEvent", f"{LOGIN}/newrepo", "2026-10-13T10:00:00Z",
           {"ref_type": "repository", "description": "A tiny Rust experiment."}),
    _event(294, "ReleaseEvent", f"{LOGIN}/parser", "2026-10-12T10:00:00Z",
           {"action": "published", "release": {"tag_name": "v1.0", "name": "First release", "body": "It parses."}}),
    _event(293, "GollumEvent", f"{LOGIN}/parser", "2026-10-11T10:00:00Z", {"pages": []}),
    _event(292, "IssuesEvent", f"{LOGIN}/parser", "2026-10-10T10:00:00Z",
           {"action": "opened", "issue": {"number": 3, "title": "Unicode names", "body": "Names with accents break."}}),
]

REPOS = [
    {"id": 1, "full_name": f"{LOGIN}/parser", "language": "Python", "fork": False, "description": "A parser.",
     "created_at": "2024-01-01T00:00:00Z", "pushed_at": "2026-10-18T10:00:00Z"},
    {"id": 2, "full_name": f"{LOGIN}/newrepo", "language": "Rust", "fork": False, "description": "A tiny Rust experiment.",
     "created_at": "2026-10-13T10:00:00Z", "pushed_at": "2026-10-13T11:00:00Z"},
    {"id": 3, "full_name": f"{LOGIN}/borrowed", "language": "JavaScript", "fork": True,
     "created_at": "2023-01-01T00:00:00Z", "pushed_at": "2023-02-01T00:00:00Z"},
    {"id": 4, "full_name": f"{LOGIN}/docs", "language": "Python", "fork": False, "description": None,
     "created_at": "2022-05-05T00:00:00Z", "pushed_at": "2025-01-01T00:00:00Z"},
]


def _commit(sha, message, date):
    return {"sha": sha, "html_url": f"https://github.com/c/{sha}",
            "commit": {"message": message, "author": {"date": date}, "committer": {"date": date}}}


COMMITS = {
    f"{LOGIN}/parser": [_commit("c1", "Fix the tokenizer\n\nIt dropped the last token.", "2026-10-18T09:00:00Z"),
                        _commit("c2", "Add release notes", "2026-10-12T09:00:00Z")],
    f"{LOGIN}/docs": [_commit("c3", "Typo", "2025-01-01T00:00:00Z")],
}


class FakeGitHub:
    """Routes requests to fixture data and records them."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.events = list(EVENTS)
        self.etag = 'W/"e1"'
        self.status_override: dict[str, int] = {}
        self.revoke_status = 204

    def __call__(self, method, url, *, headers, data=None, json=None, auth=None):
        parsed = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(parsed.query))
        self.calls.append((method, parsed.path, {"query": q, "headers": headers, "data": data, "json": json, "auth": auth}))
        path = parsed.path
        if path in self.status_override:
            return HttpResponse(self.status_override[path], {"message": "nope"},
                                {"X-RateLimit-Remaining": "0"} if self.status_override[path] == 403 else {})
        if method == "POST" and url.startswith("https://github.com/login/oauth/access_token"):
            if data["code"] == "bad":
                return HttpResponse(200, {"error": "bad_verification_code"})
            return HttpResponse(200, {"access_token": "gho_test", "scope": "read:user", "token_type": "bearer"})
        if method == "DELETE" and path.startswith("/applications/"):
            return HttpResponse(self.revoke_status, None)
        if path == "/user":
            return HttpResponse(200, {"login": LOGIN, "id": 42})
        if path == f"/users/{LOGIN}/events":
            if headers.get("If-None-Match") == self.etag:
                return HttpResponse(304, None)
            page = int(q.get("page", 1))
            return HttpResponse(200, self.events if page == 1 else [], {"ETag": self.etag})
        if path == f"/users/{LOGIN}/repos":
            return HttpResponse(200, REPOS if int(q.get("page", 1)) == 1 else [])
        if path.startswith("/repos/") and path.endswith("/commits"):
            full = path[len("/repos/"):-len("/commits")]
            if full == f"{LOGIN}/newrepo":
                return HttpResponse(409, {"message": "Git Repository is empty."})
            assert q.get("author") == LOGIN, "commits are always filtered to the user"
            return HttpResponse(200, COMMITS.get(full, []) if int(q.get("page", 1)) == 1 else [])
        return HttpResponse(404, {"message": "Not Found"})


@pytest.fixture
def gh(monkeypatch):
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_ID", "login-client")
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_SECRET", "login-secret")
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CONNECTOR_CLIENT_ID", None)
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CONNECTOR_CLIENT_SECRET", None)
    fake = FakeGitHub()
    return GitHubConnector(request=fake), fake


def _ctx(cursor=None):
    return SyncContext(tenant_id="t", tokens=ConnectorTokens(access_token="gho_test", account_label=LOGIN), cursor=cursor or {})


# ------------------------------------------------------------------ contract and OAuth

def test_github_registers_and_meets_the_contract(gh):
    registry.load_builtin()
    conn = registry.get_connector("github")
    assert isinstance(conn, ActivityConnector)
    assert conn.privacy_weight == "low" and conn.schedule == {"cadence": "daily", "hour": 4}
    assert "does not read code, private repositories" in conn.consent_disclosure
    assert "committed" in conn.event_types() and "starred" in conn.event_types()


def test_the_connector_app_falls_back_to_the_sign_in_app(gh, monkeypatch):
    conn, _ = gh
    assert conn.is_configured()
    url = urllib.parse.urlparse(conn.authorize_url(redirect_uri="https://app/echo/connectors/github/callback",
                                                   state="s1", code_challenge="cc"))
    q = dict(urllib.parse.parse_qsl(url.query))
    assert url.netloc == "github.com" and q["client_id"] == "login-client" and q["scope"] == "read:user"
    assert q["code_challenge"] == "cc" and q["code_challenge_method"] == "S256" and q["state"] == "s1"
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CONNECTOR_CLIENT_ID", "connector-client")
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CONNECTOR_CLIENT_SECRET", "connector-secret")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(
        conn.authorize_url(redirect_uri="r", state="s", code_challenge="c")).query))
    assert q["client_id"] == "connector-client"
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CONNECTOR_CLIENT_ID", None)
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_ID", None)
    assert not conn.is_configured()


def test_the_callback_exchanges_the_code_with_its_verifier(gh):
    conn, fake = gh
    tokens = conn.handle_callback(code="good", redirect_uri="https://app/cb", code_verifier="v" * 43)
    assert tokens.access_token == "gho_test" and tokens.account_label == LOGIN and tokens.scopes == "read:user"
    sent = next(c for c in fake.calls if c[0] == "POST")[2]["data"]
    assert sent["code_verifier"] == "v" * 43 and sent["redirect_uri"] == "https://app/cb"
    with pytest.raises(ConnectorError):
        conn.handle_callback(code="bad", redirect_uri="r", code_verifier="v")


def test_revoke_deletes_the_grant_at_github(gh):
    conn, fake = gh
    conn.revoke(ConnectorTokens(access_token="gho_test"))
    method, path, info = fake.calls[-1]
    assert (method, path) == ("DELETE", "/applications/login-client/grant")
    assert info["auth"] == ("login-client", "login-secret") and info["json"] == {"access_token": "gho_test"}
    fake.revoke_status = 500
    with pytest.raises(ConnectorError):
        conn.revoke(ConnectorTokens(access_token="gho_test"))


# ------------------------------------------------------------------ backfill

def test_the_backfill_keeps_what_echo_keeps_and_text_only_the_users_own(gh):
    conn, fake = gh
    ctx = _ctx()
    events = list(conn.initial_backfill(ctx))
    by_id = {e.external_id: e for e in events}

    assert by_id["event:300"].event_type == "pushed" and by_id["event:300"].text_content is None
    assert by_id["event:300"].payload["repo"] == f"{LOGIN}/parser"
    assert by_id["event:299"].event_type == "opened_pull_request"
    assert by_id["event:299"].text_content == "Stream the tokenizer\n\nReads in chunks so big files fit."
    assert by_id["event:298"].event_type == "merged_pull_request" and by_id["event:298"].text_content is None
    assert by_id["event:297"].text_content == "Same here; a guard fixes it."
    assert by_id["event:296"].event_type == "starred" and by_id["event:296"].text_content is None
    assert by_id["event:294"].event_type == "published_release"
    assert by_id["event:292"].event_type == "opened_issue"
    assert "event:293" not in by_id, "kinds Echo does not keep are dropped"

    # A repository created inside the feed's window is recorded once.
    created = [e for e in events if e.event_type == "created_repository"]
    assert sorted(e.payload["repo"] for e in created) == [f"{LOGIN}/borrowed", f"{LOGIN}/docs", f"{LOGIN}/newrepo", f"{LOGIN}/parser"]
    assert len(created) == 4

    commits = {e.external_id: e for e in events if e.event_type == "committed"}
    assert set(commits) == {"commit:c1", "commit:c2", "commit:c3"}
    assert commits["commit:c1"].text_content == "Fix the tokenizer\n\nIt dropped the last token."
    assert commits["commit:c1"].occurred_at == datetime(2026, 10, 18, 9, tzinfo=timezone.utc)
    walked = {c[1] for c in fake.calls if c[1].endswith("/commits")}
    assert f"/repos/{LOGIN}/borrowed/commits" not in walked, "forks are not walked"
    assert f"/repos/{LOGIN}/newrepo/commits" in walked, "an empty repository is tried and skipped"

    assert ctx.cursor["newest_event_id"] == "300" and ctx.cursor["events_etag"] == 'W/"e1"' and ctx.cursor["login"] == LOGIN
    facts = {f.key: f for f in ctx.facts}
    assert set(facts) == {"Python (GitHub)", "Rust (GitHub)"}, "a fork's language is not a skill"
    assert facts["Python (GitHub)"].confidence == 0.5
    assert facts["Python (GitHub)"].value == "Main language of 2 of your public repositories"
    assert facts["Rust (GitHub)"].confidence == 0.4 and all(f.kind == "skill" for f in ctx.facts)


def test_text_is_never_kept_for_an_event_someone_else_did(gh):
    item = _event(1, "IssueCommentEvent", "x/y", "2026-10-01T00:00:00Z",
                  {"action": "created", "comment": {"body": "not my words"}}, actor="someone-else")
    assert GitHubConnector.map_event(item, LOGIN).text_content is None


# ------------------------------------------------------------------ incremental

def test_an_unchanged_feed_costs_one_conditional_request(gh):
    conn, fake = gh
    ctx = _ctx({"newest_event_id": "300", "events_etag": fake.etag, "login": LOGIN})
    events = list(conn.incremental_sync(ctx, datetime(2026, 10, 18, 12)))
    assert events == []
    feed_calls = [c for c in fake.calls if c[1].endswith("/events")]
    assert len(feed_calls) == 1 and feed_calls[0][2]["headers"]["If-None-Match"] == fake.etag
    assert not [c for c in fake.calls if c[1].endswith("/commits")]


def test_incremental_stops_at_the_last_seen_event_and_walks_pushed_repos(gh):
    conn, fake = gh
    fake.etag = 'W/"e2"'
    fake.events = [
        _event(302, "PushEvent", f"{LOGIN}/parser", "2026-10-19T08:00:00Z", {"ref": "refs/heads/main", "head": "h302"}),
        _event(301, "WatchEvent", "other/thing", "2026-10-19T07:00:00Z"),
    ] + EVENTS
    ctx = _ctx({"newest_event_id": "300", "events_etag": 'W/"e1"', "login": LOGIN})
    events = list(conn.incremental_sync(ctx, datetime(2026, 10, 18, 12)))
    ids = [e.external_id for e in events]
    assert ids[:2] == ["event:302", "event:301"] and "event:300" not in ids
    commit_calls = [c for c in fake.calls if c[1].endswith("/commits")]
    assert [c[1] for c in commit_calls] == [f"/repos/{LOGIN}/parser/commits"]
    assert commit_calls[0][2]["query"]["since"] == "2026-10-18T12:00:00Z"
    assert ctx.cursor["newest_event_id"] == "302" and ctx.cursor["events_etag"] == 'W/"e2"'


# ------------------------------------------------------------------ failures

def test_a_refused_token_asks_to_reconnect_and_a_spent_limit_does_not(gh):
    conn, fake = gh
    fake.status_override[f"/users/{LOGIN}/events"] = 401
    with pytest.raises(ConnectorError) as e:
        list(conn.initial_backfill(_ctx()))
    assert e.value.auth is True
    fake.status_override[f"/users/{LOGIN}/events"] = 403
    with pytest.raises(ConnectorError) as e:
        list(conn.initial_backfill(_ctx()))
    assert e.value.auth is False and "hourly limit" in str(e.value)


# ------------------------------------------------------------------ through the runtime

def test_connect_sync_and_disconnect_github_end_to_end(unauthenticated_client, db, gh, monkeypatch):
    from app.models.activity_event import ActivityEvent
    from app.models.echo_connector import EchoConnectorCredential, EchoConnectorGrant
    from app.models.personal_context import PersonalContext
    from app.services import auth_service

    conn, fake = gh
    registry.register_connector(conn)  # the fake-backed instance replaces the real one
    monkeypatch.setattr(settings, "ECHO_CONNECTOR_SYNC", "inline")
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://app.example")
    import app.database as database

    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    try:
        user = auth_service.create_user(db, email="gh-e2e@example.com", password="pw" * 6)
        user.tier = "studio"
        db.commit()
        token, _ = auth_service.create_access_token(user.id)
        h = {"Authorization": f"Bearer {token}"}

        r = unauthenticated_client.post("/api/v1/echo/connectors/github/authorize",
                                        json={"consent_version": conn.consent_version}, headers=h)
        assert r.status_code == 200, r.text
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.json()["authorize_url"]).query))["state"]
        r = unauthenticated_client.post("/api/v1/echo/connectors/github/callback",
                                        json={"code": "good", "state": state}, headers=h)
        assert r.status_code == 200, r.text
        grant = r.json()["grant"]
        assert grant["account_label"] == LOGIN and grant["status"] == "idle"
        assert grant["events"] == db.query(ActivityEvent).filter_by(tenant_id=user.id, connector="github").count() > 10

        mine = db.query(ActivityEvent).filter_by(tenant_id=user.id, external_id="commit:c1").one()
        assert mine.text_content.startswith("Fix the tokenizer")
        skills = db.query(PersonalContext).filter_by(user_id=user.id, source="connector:github").all()
        assert {s.key for s in skills} == {"Python (GitHub)", "Rust (GitHub)"} and max(s.confidence for s in skills) <= 0.8

        feed = unauthenticated_client.get("/api/v1/echo/activity", params={"connector": "github", "limit": 3}, headers=h).json()
        assert [i["event_type"] for i in feed["items"]][0] == "pushed"

        r = unauthenticated_client.delete("/api/v1/echo/connectors/github", headers=h)
        assert r.status_code == 200 and r.json()["provider_revoked"] is True
        assert any(c[0] == "DELETE" and c[1] == "/applications/login-client/grant" for c in fake.calls)
        assert db.query(ActivityEvent).filter_by(tenant_id=user.id, connector="github").count() == 0
        assert db.query(EchoConnectorCredential).filter_by(tenant_id=user.id).count() == 0
        assert db.query(EchoConnectorGrant).filter_by(tenant_id=user.id).count() == 0
        assert db.query(PersonalContext).filter_by(user_id=user.id, source="connector:github").count() == 0
    finally:
        registry.register_connector(GitHubConnector())  # restore the real one
