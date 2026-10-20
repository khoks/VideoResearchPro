"""GitHub activity connector (S-3.2.4).

Reads a user's **public** GitHub activity with ``read:user``: the events feed
(pushes, pull requests, reviews, issues, comments, repositories created,
stars, forks, releases), the commits they authored in their own
repositories, and the languages of those repositories.

Three facts about the API shape this module:

* The events feed holds only the last **300 events / 30 days**, so the
  backfill walks commits per repository and syncs run nightly.
* Since GitHub's 2025-08 Events API change, push events no longer carry the
  commit list. A push is recorded as ``pushed`` (repository, branch, head);
  commit messages come from ``GET /repos/{repo}/commits?author=<login>``,
  which also guarantees the words are the user's own: they are what voice
  signals (E-3.3) read, so a teammate's commit message must never land in
  ``text_content``.
* 5,000 requests per hour. A backfill is about 50 requests (three event
  pages, up to three repository pages, two commit pages for each of the 20
  most recently pushed repositories); a nightly sync is a handful, and an
  unchanged feed costs nothing (``If-None-Match``).

Text kept as the user's own words: commit messages, and the titles and bodies
of pull requests, issues, reviews, comments and releases the user wrote.
Repository names, branch names and star targets are metadata only.
"""
from __future__ import annotations

import logging
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

import httpx

from app.config import settings
from app.connectors.base import (
    ActivityEvent,
    ConnectorError,
    ConnectorTokens,
    DerivedFact,
    SyncContext,
)

logger = logging.getLogger(__name__)

API = "https://api.github.com"
AUTHORIZE = "https://github.com/login/oauth/authorize"
TOKEN = "https://github.com/login/oauth/access_token"
SCOPE = "read:user"

EVENT_PAGES = 3  # 3 x 100 = the feed's 300-event ceiling
REPO_PAGES = 3
COMMIT_REPOS = 20  # most recently pushed own repositories walked on backfill
COMMIT_PAGES = 2  # x 100 commits each
TEXT_MAX = 4000

DISCLOSURE = """Echo reads your public GitHub activity: the commits you push, with their messages; the pull requests, issues, reviews, comments and releases you write; the repositories you create, star or fork; and the languages of your own repositories.

It does not read code, private repositories, or anything you have not made public.

What you wrote (commit messages, pull request and issue text, comments) is kept as your own words so Echo can learn how you write. The languages become skills Echo thinks you have, marked as guesses.

Echo checks once a day. GitHub keeps only the last 30 days of activity, so on the first sync Echo also reads your commits from your own repositories."""


def _client_id() -> str | None:
    return settings.OAUTH_GITHUB_CONNECTOR_CLIENT_ID or settings.OAUTH_GITHUB_CLIENT_ID


def _client_secret() -> str | None:
    if settings.OAUTH_GITHUB_CONNECTOR_CLIENT_ID:
        return settings.OAUTH_GITHUB_CONNECTOR_CLIENT_SECRET
    return settings.OAUTH_GITHUB_CLIENT_SECRET


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _text(*parts: str | None) -> str | None:
    text = "\n\n".join(p.strip() for p in parts if p and p.strip())
    return text[:TEXT_MAX] or None


class HttpResponse:
    """What the connector needs from a response; a seam for tests."""

    def __init__(self, status: int, data: Any, headers: dict[str, str] | None = None):
        self.status = status
        self.data = data
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


def _default_request(method: str, url: str, *, headers: dict, data: dict | None = None,
                     json: dict | None = None, auth: tuple[str, str] | None = None) -> HttpResponse:
    with httpx.Client(timeout=20.0) as client:
        resp = client.request(method, url, headers=headers, data=data, json=json, auth=auth)
    try:
        body = resp.json() if resp.content else None
    except ValueError:
        body = None
    return HttpResponse(resp.status_code, body, dict(resp.headers))


class GitHubConnector:
    name = "github"
    display_name = "GitHub"
    privacy_weight = "low"
    consent_disclosure = DISCLOSURE
    consent_version = "2026-10-19"
    schedule = {"cadence": "daily", "hour": 4}

    EVENT_TYPES = [
        "pushed",
        "committed",
        "opened_pull_request",
        "merged_pull_request",
        "reviewed_pull_request",
        "opened_issue",
        "commented",
        "published_release",
        "created_repository",
        "starred",
        "forked",
    ]

    def __init__(self, request: Callable[..., HttpResponse] | None = None):
        self._request = request or _default_request

    # ----------------------------------------------------------------- contract

    def event_types(self) -> list[str]:
        return list(self.EVENT_TYPES)

    def is_configured(self) -> bool:
        return bool(_client_id() and _client_secret())

    def authorize_url(self, *, redirect_uri: str, state: str, code_challenge: str) -> str:
        params = {
            "client_id": _client_id(),
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "allow_signup": "false",
        }
        return f"{AUTHORIZE}?{urllib.parse.urlencode(params)}"

    def handle_callback(self, *, code: str, redirect_uri: str, code_verifier: str) -> ConnectorTokens:
        resp = self._request(
            "POST", TOKEN,
            headers={"Accept": "application/json"},
            data={
                "client_id": _client_id(), "client_secret": _client_secret(), "code": code,
                "redirect_uri": redirect_uri, "code_verifier": code_verifier,
            },
        )
        body = resp.data if isinstance(resp.data, dict) else {}
        token = body.get("access_token")
        if resp.status != 200 or not token:
            raise ConnectorError(f"GitHub did not issue a token: {body.get('error') or resp.status}")
        expires_at = None
        if body.get("expires_in"):
            expires_at = datetime.now(timezone.utc).timestamp() + int(body["expires_in"])
            expires_at = datetime.fromtimestamp(expires_at, tz=timezone.utc)
        user = self._api(token, "/user")
        return ConnectorTokens(
            access_token=token,
            refresh_token=body.get("refresh_token"),
            expires_at=expires_at,
            scopes=body.get("scope") or SCOPE,
            account_label=(user.data or {}).get("login"),
        )

    def revoke(self, tokens: ConnectorTokens) -> None:
        client_id, secret = _client_id(), _client_secret()
        if not (client_id and secret):
            raise ConnectorError("GitHub connector is not configured")
        resp = self._request(
            "DELETE", f"{API}/applications/{client_id}/grant",
            headers={"Accept": "application/vnd.github+json"},
            json={"access_token": tokens.access_token},
            auth=(client_id, secret),
        )
        if resp.status not in (204, 404):
            raise ConnectorError(f"GitHub refused the revoke ({resp.status})")

    def initial_backfill(self, ctx: SyncContext) -> Iterator[ActivityEvent]:
        login = self._login(ctx)
        feed = list(self._feed(ctx, login, stop_at=None))
        yield from feed
        created_in_feed = {e.payload.get("repo") for e in feed if e.event_type == "created_repository"}
        repos = self._own_repos(ctx, login)
        ctx.facts.extend(self.language_facts(repos))
        for repo in repos:
            created = _parse_time(repo.get("created_at"))
            if created and repo.get("full_name") not in created_in_feed:
                yield ActivityEvent(
                    external_id=f"repo:{repo['id']}", event_type="created_repository", occurred_at=created,
                    payload={"repo": repo.get("full_name"), "language": repo.get("language"), "via": "repositories"},
                    text_content=_text(repo.get("description")),
                )
        recent = sorted(
            (r for r in repos if not r.get("fork") and r.get("pushed_at")),
            key=lambda r: r["pushed_at"], reverse=True,
        )[:COMMIT_REPOS]
        for repo in recent:
            yield from self._commits(ctx, login, repo["full_name"], since=None)

    def incremental_sync(self, ctx: SyncContext, since: datetime | None) -> Iterator[ActivityEvent]:
        login = self._login(ctx)
        pushed_repos: set[str] = set()
        for ev in self._feed(ctx, login, stop_at=ctx.cursor.get("newest_event_id")):
            if ev.event_type == "pushed" and ev.payload.get("repo"):
                pushed_repos.add(ev.payload["repo"])
            yield ev
        for full_name in sorted(pushed_repos):
            yield from self._commits(ctx, login, full_name, since=since)
        # Languages drift slowly; one page of repositories keeps the guess fresh.
        ctx.facts.extend(self.language_facts(self._own_repos(ctx, login, pages=1)))

    # ----------------------------------------------------------------- helpers

    def _api(self, token: str, path: str, params: dict | None = None,
             etag: str | None = None) -> HttpResponse:
        url = path if path.startswith("http") else f"{API}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if etag:
            headers["If-None-Match"] = etag
        resp = self._request("GET", url, headers=headers)
        if resp.status == 401:
            raise ConnectorError("GitHub refused the access token", auth=True)
        if resp.status == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
            raise ConnectorError("GitHub's hourly limit is used up; the next sync will continue")
        if resp.status not in (200, 304):
            raise ConnectorError(f"GitHub answered {resp.status} for {path}")
        return resp

    def _login(self, ctx: SyncContext) -> str:
        login = ctx.tokens.account_label or ctx.cursor.get("login")
        if not login:
            login = (self._api(ctx.tokens.access_token, "/user").data or {}).get("login")
        if not login:
            raise ConnectorError("GitHub did not say who the token belongs to", auth=True)
        ctx.cursor["login"] = login
        return login

    def _feed(self, ctx: SyncContext, login: str, stop_at: str | None) -> Iterator[ActivityEvent]:
        newest: str | None = None
        for page in range(1, EVENT_PAGES + 1):
            etag = ctx.cursor.get("events_etag") if page == 1 and stop_at else None
            resp = self._api(ctx.tokens.access_token, f"/users/{login}/events", {"per_page": 100, "page": page}, etag=etag)
            if resp.status == 304:
                return  # nothing new; costs no rate limit
            if page == 1 and resp.headers.get("etag"):
                ctx.cursor["events_etag"] = resp.headers["etag"]
            items = resp.data if isinstance(resp.data, list) else []
            for item in items:
                eid = str(item.get("id", ""))
                if stop_at and eid and int(eid) <= int(stop_at):
                    if newest:
                        ctx.cursor["newest_event_id"] = newest
                    return
                if newest is None and eid:
                    newest = eid
                ev = self.map_event(item, login)
                if ev is not None:
                    yield ev
            if len(items) < 100:
                break
        if newest:
            ctx.cursor["newest_event_id"] = newest

    def _own_repos(self, ctx: SyncContext, login: str, pages: int = REPO_PAGES) -> list[dict]:
        out: list[dict] = []
        for page in range(1, pages + 1):
            resp = self._api(ctx.tokens.access_token, f"/users/{login}/repos",
                             {"type": "owner", "sort": "pushed", "per_page": 100, "page": page})
            items = resp.data if isinstance(resp.data, list) else []
            out.extend(items)
            if len(items) < 100:
                break
        return out

    def _commits(self, ctx: SyncContext, login: str, full_name: str, since: datetime | None) -> Iterator[ActivityEvent]:
        params: dict[str, Any] = {"author": login, "per_page": 100}
        if since is not None:
            # Stored times are naive UTC.
            aware = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
            params["since"] = aware.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for page in range(1, COMMIT_PAGES + 1):
            try:
                resp = self._api(ctx.tokens.access_token, f"/repos/{full_name}/commits", {**params, "page": page})
            except ConnectorError as e:
                if e.auth or "hourly limit" in str(e):
                    raise
                # An empty or deleted repository answers 409/404: skip it.
                logger.info("github: skipping commits of %s: %s", full_name, e)
                return
            items = resp.data if isinstance(resp.data, list) else []
            for c in items:
                commit = c.get("commit") or {}
                when = _parse_time((commit.get("author") or {}).get("date")) or _parse_time((commit.get("committer") or {}).get("date"))
                sha = c.get("sha")
                if not sha or when is None:
                    continue
                yield ActivityEvent(
                    external_id=f"commit:{sha}", event_type="committed", occurred_at=when,
                    payload={"repo": full_name, "sha": sha, "url": c.get("html_url")},
                    text_content=_text(commit.get("message")),
                )
            if len(items) < 100:
                break

    @staticmethod
    def language_facts(repos: list[dict]) -> list[DerivedFact]:
        counts = Counter(r["language"] for r in repos if r.get("language") and not r.get("fork"))
        facts = []
        for language, n in counts.most_common(15):
            # The key names its source so a sync never overwrites a skill the
            # user wrote themselves ("Python" stays theirs; this is a guess).
            facts.append(DerivedFact(
                kind="skill",
                key=f"{language} (GitHub)",
                value=f"Main language of {n} of your public repositories" if n > 1
                else "Main language of one of your public repositories",
                confidence=round(min(0.8, 0.4 + 0.1 * (n - 1)), 2),
            ))
        return facts

    @staticmethod
    def map_event(item: dict, login: str) -> ActivityEvent | None:
        """One feed item to one event, or None for kinds Echo does not keep.
        Text only where the user wrote it (the actor is the token's user)."""
        kind = item.get("type")
        when = _parse_time(item.get("created_at"))
        eid = item.get("id")
        if not kind or when is None or not eid:
            return None
        repo = (item.get("repo") or {}).get("name")
        p = item.get("payload") or {}
        base = {"repo": repo, "github_event": kind}
        mine = ((item.get("actor") or {}).get("login") or "").lower() == login.lower()

        def ev(event_type: str, payload: dict | None = None, text: str | None = None) -> ActivityEvent:
            return ActivityEvent(
                external_id=f"event:{eid}", event_type=event_type, occurred_at=when,
                payload={**base, **(payload or {})}, text_content=text if mine else None,
            )

        if kind == "PushEvent":
            return ev("pushed", {"ref": p.get("ref"), "head": p.get("head")})
        if kind == "PullRequestEvent":
            pr = p.get("pull_request") or {}
            info = {"number": p.get("number") or pr.get("number"), "title": pr.get("title"), "url": pr.get("html_url")}
            if p.get("action") == "opened":
                return ev("opened_pull_request", info, _text(pr.get("title"), pr.get("body")))
            if p.get("action") == "closed" and pr.get("merged"):
                return ev("merged_pull_request", info)
            return None
        if kind == "PullRequestReviewEvent":
            review = p.get("review") or {}
            pr = p.get("pull_request") or {}
            return ev("reviewed_pull_request",
                      {"state": review.get("state"), "title": pr.get("title"), "url": review.get("html_url")},
                      _text(review.get("body")))
        if kind == "IssuesEvent" and p.get("action") == "opened":
            issue = p.get("issue") or {}
            return ev("opened_issue", {"number": issue.get("number"), "title": issue.get("title"), "url": issue.get("html_url")},
                      _text(issue.get("title"), issue.get("body")))
        if kind in ("IssueCommentEvent", "PullRequestReviewCommentEvent", "CommitCommentEvent") and p.get("action", "created") == "created":
            comment = p.get("comment") or {}
            subject = (p.get("issue") or p.get("pull_request") or {}).get("title")
            return ev("commented", {"title": subject, "url": comment.get("html_url")}, _text(comment.get("body")))
        if kind == "ReleaseEvent" and p.get("action") == "published":
            rel = p.get("release") or {}
            return ev("published_release", {"tag": rel.get("tag_name"), "title": rel.get("name"), "url": rel.get("html_url")},
                      _text(rel.get("name"), rel.get("body")))
        if kind == "CreateEvent" and p.get("ref_type") == "repository":
            return ev("created_repository", {"description": p.get("description")}, _text(p.get("description")))
        if kind == "WatchEvent":
            return ev("starred")
        if kind == "ForkEvent":
            return ev("forked", {"fork": (p.get("forkee") or {}).get("full_name")})
        return None
