"""The docs that restate the code, read against the code (I-4, T-5.6.7).

CLAUDE.md told every session the test suite held 168 tests when it held 3,200,
and `.env.example` existed three times with different defaults, because nothing
compared them with anything. A failure here is a doc to update, not a test to
relax: a new `Settings` field goes in `.env.example` and in CLAUDE.md's table,
a new route in CLAUDE.md's list and in docs/api-reference.md.
"""
from __future__ import annotations

import ast
import functools
import itertools
import os
import re
from pathlib import Path

import pytest
from fastapi.routing import APIWebSocketRoute
from pydantic import TypeAdapter

from app.config import Settings
from app.main import app
from app.models.job_video import JobVideo
from app.routers.ws import router as ws_router
from app.services import llm_routing

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / ".env.example"
FIELDS = Settings.model_fields
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

SECRET_NAME = re.compile(r"(_KEY|_SECRET|_PASSWORD|_TOKEN)$")
GROUP_LINE = re.compile(r"^# ===== (.+) =====$")
ASSIGNMENT = re.compile(r"^(?:# )?([A-Z][A-Z0-9_]+)=(.*)$")
ROUTE_LINE = re.compile(r"^(?P<methods>(?:GET|POST|PUT|PATCH|DELETE|WS)(?:/(?:GET|POST|PUT|PATCH|DELETE))*)\s+(?P<path>/\S+)", re.M)
ROUTE_MENTION = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|WS)\s+`?(/[^\s`),]+)")
SKIPPED_DIRS = {".claude", ".git", ".venv", "__pycache__", "data", "dist", "node_modules", "venv"}
UNREAD = "Not read by any code"
LEGACY = re.compile(r"videoresearchpro[\w.]*\w", re.IGNORECASE)


def _claude_section(start: str, end: str) -> str:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    return text[text.index(start):text.index(end)]


def _template() -> dict[str, dict]:
    """Every assignment in the template, live or commented, with its group and
    whether the line above says nothing reads it."""
    rows: dict[str, dict] = {}
    group = None
    above = ""
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        if m := GROUP_LINE.match(line):
            group = m.group(1)
        elif m := ASSIGNMENT.match(line):
            name, value = m.groups()
            assert name not in rows, f"{name} is listed twice"
            rows[name] = {"group": group, "value": value, "live": not line.startswith("#"), "unread": UNREAD in above}
        above = line
    return rows


def _settings_rows() -> dict[str, dict]:
    return {k: v for k, v in _template().items() if not k.startswith("VITE_")}


def _env_table() -> dict[str, dict]:
    """CLAUDE.md's table: each name with its group and its default cell."""
    rows: dict[str, dict] = {}
    group = None
    for line in _claude_section("## Environment Variables", "\\* One provider key").splitlines():
        if not line.startswith("|") or line.startswith(("|---", "| Variable")):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        if m := re.fullmatch(r"\*\*(.+)\*\*", cells[0]):
            group = m.group(1)
            continue
        names = re.findall(r"`([A-Z][A-Z0-9_]+)`", cells[0])
        defaults = [d.strip() for d in cells[2].split(" / ")]
        assert len(names) == len(defaults), f"{names} has defaults {defaults}"
        for name, default in zip(names, defaults):
            assert name not in rows, f"{name} has two rows"
            rows[name] = {"group": group, "default": default, "note": cells[3]}
    return rows


def _key(method: str, path: str) -> tuple[str, str]:
    return method, re.sub(r"\{[^}]*\}", "{}", path.split("?")[0].rstrip("/"))


def _routes() -> set[tuple[str, str]]:
    """What the app serves, read through OpenAPI. `app.routes` is no public
    list of them: FastAPI 0.162, which CI installs, wraps each included router
    in a private `_IncludedRouter`. The schema has no WebSockets, so those come
    from their router. Every HTTP route is in the schema: nothing sets
    `include_in_schema=False`."""
    found = {
        _key(method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.upper() in HTTP_METHODS
    }
    found.update(_key("WS", r.path) for r in ws_router.routes if isinstance(r, APIWebSocketRoute))
    assert len(found) > 150, "the app's routes did not load"
    assert ("WS", "/ws/jobs") in found, "the progress socket did not load"
    return found


# ── .env.example ─────────────────────────────────────────────────────────


def test_there_is_exactly_one_env_template() -> None:
    """D-112: the root file. Three copies had drifted apart: the backend's said
    0.5 s between transcript fetches, the pace that got the install IP-blocked."""
    found = []
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
        found.extend(Path(folder) / f for f in files if f == ".env.example")
    assert found == [TEMPLATE]


def test_every_settings_field_is_in_the_template() -> None:
    missing = sorted(set(FIELDS) - set(_settings_rows()))
    assert not missing, f"add to .env.example: {missing}"


def test_the_template_lists_nothing_settings_does_not_have() -> None:
    unknown = sorted(set(_settings_rows()) - set(FIELDS))
    assert not unknown, f"not in app/config.py: {unknown}"


@pytest.mark.parametrize("name", sorted(FIELDS))
def test_the_template_shows_each_default(name: str) -> None:
    if SECRET_NAME.search(name):
        return  # blank, by the next test
    field = FIELDS[name]
    parsed = TypeAdapter(field.annotation).validate_python(_settings_rows()[name]["value"])
    assert (parsed or None) == (field.default or None), f".env.example says {parsed!r}"


def test_secrets_are_blank() -> None:
    filled = sorted(n for n, r in _settings_rows().items() if SECRET_NAME.search(n) and r["value"])
    assert not filled, f"a template holds no secret or sample secret: {filled}"
    # The name rule found them: a rename that dodges it should fail here.
    assert {"JWT_SECRET", "BYOK_ENCRYPTION_KEY", "OPENAI_API_KEY", "SMTP_PASSWORD", "TWITTER_BEARER_TOKEN"} <= {
        n for n in FIELDS if SECRET_NAME.search(n)
    }


def test_a_copy_of_the_template_changes_nothing_but_secrets() -> None:
    """Commented lines are documentation: only a blank secret is live, so an
    untouched copy behaves like no `.env` at all."""
    live = {n for n, r in _settings_rows().items() if r["live"]}
    assert live == {n for n in live if SECRET_NAME.search(n)}
    assert {"OPENAI_API_KEY", "YOUTUBE_API_KEY", "JWT_SECRET", "BYOK_ENCRYPTION_KEY"} <= live


def test_a_copy_of_the_template_boots(monkeypatch) -> None:
    """Through the loader production uses. A blank `JWT_SECRET=` must fall back
    to the development value: PyJWT refuses an empty key."""
    for name in FIELDS:
        monkeypatch.delenv(name, raising=False)
    loaded = Settings(_env_file=TEMPLATE, _env_file_encoding="utf-8")
    assert loaded.JWT_SECRET == FIELDS["JWT_SECRET"].default
    assert loaded.CHROMA_GLOBAL_COLLECTION_NAME == "pratidhvani_global"
    assert not loaded.BYOK_ENCRYPTION_KEY


def test_the_template_points_at_the_use_case_defaults() -> None:
    """CLAUDE.md's list names each use case but shows no default."""
    line = next(x for x in TEMPLATE.read_text(encoding="utf-8").splitlines() if "Every use case" in x)
    assert "CLAUDE.md" not in line
    assert "/account/ai-models" in line and "USE_CASE_REGISTRY" in line


def test_the_template_says_the_proxy_target_is_a_shell_variable() -> None:
    """vite.config.ts reads process.env, which Vite does not fill from a .env
    file, so a value in frontend/.env is ignored and the dev proxy keeps sending
    /api to port 8000: on this machine, the owner's live backend."""
    config = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    assert "process.env.VITE_PROXY_TARGET" in config
    assert "loadEnv" not in config, "the proxy target now reads .env: say so in .env.example"
    lines = TEMPLATE.read_text(encoding="utf-8").splitlines()
    above = lines[:next(i for i, x in enumerate(lines) if x.startswith("# VITE_PROXY_TARGET="))]
    comment = " ".join(itertools.takewhile(lambda x: not ASSIGNMENT.match(x), reversed(above)))
    assert "shell" in comment and "process.env" in comment
    assert not any("reads these from frontend/.env" in x for x in lines)


# ── CLAUDE.md: the env table ─────────────────────────────────────────────


def test_every_settings_field_has_a_row_in_the_env_table() -> None:
    missing = sorted(set(FIELDS) - set(_env_table()))
    assert not missing, f"add to CLAUDE.md: {missing}"


def test_the_env_table_documents_nothing_that_does_not_exist() -> None:
    unknown = sorted(set(_env_table()) - set(FIELDS))
    assert not unknown, f"not in app/config.py: {unknown}"


@pytest.mark.parametrize("name", sorted(FIELDS))
def test_the_env_table_shows_each_default(name: str) -> None:
    if name == "JWT_SECRET":
        return  # described, not quoted
    default = FIELDS[name].default
    expected = {"(unset)", "(empty)"} if default in (None, "") else {f"`{default}`"}
    assert _env_table()[name]["default"] in expected


def test_the_template_and_the_env_table_use_the_same_groups() -> None:
    template = {n: r["group"] for n, r in _settings_rows().items()}
    table = {n: r["group"] for n, r in _env_table().items()}
    moved = sorted(n for n in FIELDS if template[n] != table[n])
    assert not moved, f"grouped differently: {moved}"


@functools.lru_cache
def _unread_settings() -> frozenset[str]:
    """Fields nothing reads: no attribute of that name (`settings.X`) and no
    string that is exactly the name (`getattr(settings, "X")`) in code that runs.
    Comments and docstrings do not count, which is the point: three of them still
    described `LLM_MAX_CONTEXT_TOKENS` as if it took effect."""
    read: set[str] = set()
    for folder in ("app", "scripts", "alembic"):
        for path in (ROOT / "backend" / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute):
                    read.add(node.attr)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    read.add(node.value)
    return frozenset(FIELDS) - read


def test_the_env_table_marks_exactly_the_settings_nothing_reads() -> None:
    marked = {n for n, r in _env_table().items() if UNREAD in r["note"]}
    assert marked == _unread_settings()


def test_the_template_marks_exactly_the_settings_nothing_reads() -> None:
    marked = {n for n, r in _settings_rows().items() if r["unread"]}
    assert marked == _unread_settings()


def test_no_use_case_summary_leans_on_a_setting_nothing_reads() -> None:
    """The summaries reach /account/ai-models."""
    unread = _unread_settings()
    stale = {k: n for k, info in llm_routing.USE_CASE_REGISTRY.items() for n in unread if n in info.summary}
    assert not stale


# ── CLAUDE.md: counts and names ──────────────────────────────────────────


def test_every_use_case_is_listed() -> None:
    section = _claude_section("### Registered use cases", "## LLM startup smoke check")
    listed = set(re.findall(r"^- `([a-z_]+)` —", section, re.M))
    assert listed == set(llm_routing.USE_CASE_REGISTRY)


def test_the_use_case_counts_are_right() -> None:
    count = len(llm_routing.USE_CASE_REGISTRY)
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert f"{count} named call sites" in text
    assert f"all {count} entries" in text


def test_the_agents_line_is_right() -> None:
    agents = sorted((ROOT / "backend" / "app" / "agents").glob("*_agent.py"))
    graphs = [p for p in agents if "StateGraph(" in p.read_text(encoding="utf-8")]
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert f"{len(agents)} agents in `app/agents/`: {len(graphs)} LangGraph graphs" in text
    unnamed = [p.name for p in agents if p.name not in text]
    assert not unnamed, f"name in CLAUDE.md: {unnamed}"


def test_the_auth_line_names_what_shipped() -> None:
    routes = {path for _, path in _routes()}
    assert any("/auth/oauth/" in p for p in routes)
    assert any("/auth/mfa/" in p for p in routes)
    assert any("/auth/sessions" in p for p in routes)
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if x.startswith("- **Auth**"))
    assert "OAuth" in line and "two-step" in line and "sessions" in line


# ── The legacy name ──────────────────────────────────────────────────────


@functools.lru_cache
def _legacy_strings() -> frozenset[str]:
    """Each form of the old name in code that runs. The tests hard-code them too,
    so they stay out of this scan."""
    sources = [ROOT / "backend" / "alembic.ini", *(ROOT / "backend" / "app").rglob("*.py")]
    for pattern in ("*.ts", "*.tsx"):
        sources += [p for p in (ROOT / "frontend" / "src").rglob(pattern) if "__tests__" not in p.parts]
    return frozenset(m for path in sources for m in LEGACY.findall(path.read_text(encoding="utf-8")))


def test_the_scan_finds_the_browser_keys() -> None:
    assert {"videoresearchpro.authToken", "videoresearchpro.authUser", "videoresearchpro.db"} <= _legacy_strings()


def test_claude_md_names_every_legacy_string() -> None:
    """So a brand cleanup does not take one for an oversight: renaming the
    browser keys signs every browser out."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    note = next(x for x in text.splitlines() if x.startswith("> **Legacy name.**"))
    missing = sorted(s for s in _legacy_strings() if s not in note)
    assert not missing, f"name in CLAUDE.md's Legacy name note: {missing}"
    assert "signs every browser out" in note


def test_the_runbook_table_names_every_legacy_string() -> None:
    text = (ROOT / "docs" / "migration-code-identifiers.md").read_text(encoding="utf-8")
    table = text[text.index("## What's renaming"):text.index("## Why these two")]
    missing = sorted(s for s in _legacy_strings() if s not in table)
    assert not missing, f"it calls its table the only legacy strings: {missing}"
    assert "signs every browser out" in table


def test_the_runbook_says_alembic_does_not_follow_database_url() -> None:
    """backend/alembic/env.py reads `sqlalchemy.url` from alembic.ini alone."""
    env = (ROOT / "backend" / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "DATABASE_URL" not in env and "settings" not in env
    text = (ROOT / "docs" / "migration-code-identifiers.md").read_text(encoding="utf-8")
    assert "alembic.ini" in text[text.index("## What's renaming"):text.index("## Why these two")]


# ── The README ───────────────────────────────────────────────────────────


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_readme_gives_the_real_collection_default() -> None:
    assert "videoresearchpro_global" not in _readme()
    assert FIELDS["CHROMA_GLOBAL_COLLECTION_NAME"].default in _readme()


def test_the_readme_has_no_stale_test_count() -> None:
    line = next(x for x in _readme().splitlines() if "pytest tests" in x)
    assert "3,700+" in line


def test_the_readme_names_every_agent() -> None:
    line = next(x for x in _readme().splitlines() if "agents/" in x)
    agents = (p.stem.removesuffix("_agent") for p in (ROOT / "backend" / "app" / "agents").glob("*_agent.py"))
    missing = [name for name in agents if name not in line]
    assert not missing, f"add to README.md's tree: {missing}"


# ── The API lists ────────────────────────────────────────────────────────


def _claude_routes() -> set[tuple[str, str]]:
    section = _claude_section("## API Endpoints", "## Environment Variables")
    return {
        _key(method, m.group("path"))
        for m in ROUTE_LINE.finditer(section)
        for method in m.group("methods").split("/")
    }


def test_every_route_is_in_claude_md() -> None:
    missing = sorted(_routes() - _claude_routes())
    assert not missing, f"add to CLAUDE.md: {missing}"


def test_claude_md_lists_no_route_that_does_not_exist() -> None:
    unknown = sorted(_claude_routes() - _routes())
    assert not unknown, f"no such route: {unknown}"


def test_every_route_is_in_the_api_reference() -> None:
    """One way only: the reference's prose also names retired routes and
    GitHub's API."""
    text = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")
    documented = {
        _key(method, path if path.startswith(("/api/v1", "/ws")) else f"/api/v1{path}")
        for method, path in ROUTE_MENTION.findall(text)
    }
    missing = sorted(_routes() - documented)
    assert not missing, f"add to docs/api-reference.md: {missing}"


def _reference() -> str:
    return (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")


def test_the_reference_says_what_answers_429() -> None:
    """It said 429 was reserved for a YouTube cap that does not exist. A client
    that believed it told a user over their quota that YouTube ran out."""
    line = next(x for x in _reference().splitlines() if x.startswith("- **Errors**"))
    assert "YouTube" not in line
    for cause in ("rate limit", "`QuotaExceededError`", "document cap", "concurrent jobs", "daily_cap", "locked"):
        assert cause in line, f"the Errors convention leaves out {cause}"


@pytest.mark.parametrize("doc", ["CLAUDE.md", "README.md", "docs/api-reference.md", "docs/architecture.md"])
def test_the_join_table_goes_by_its_real_name(doc: str) -> None:
    assert JobVideo.__tablename__ == "job_documents"
    assert "job_videos" not in (ROOT / doc).read_text(encoding="utf-8")


def test_the_library_listing_is_described_as_the_callers() -> None:
    """D-063: `documents` is global, what this route lists is not."""
    text = _reference()
    start = text.index("### `GET /api/v1/library/videos`")
    body = text[start:].splitlines()[1]
    assert "global" not in body.split("Returns")[0]
    assert "caller" in body.split("Returns")[0]


def test_the_reference_does_not_claim_no_doc_lists_endpoints() -> None:
    """CLAUDE.md lists every route, and the tests above hold it to the app."""
    assert "rather than duplicating endpoint lists" not in _reference()
