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
import importlib
import itertools
import json
import os
import pkgutil
import re
from pathlib import Path

import pytest
from fastapi.routing import APIWebSocketRoute
from pydantic import TypeAdapter
from sqlalchemy import String

import app.models as app_models
from app.agents import echo_agent
from app.config import Settings
from app.database import Base
from app.main import app
from app.models.job_video import JobVideo
from app.routers.ws import router as ws_router
from app.schemas.usage import UsageAmounts
from app.services import llm_routing, scheduler_service

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
LEGACY = re.compile(r"videoresearchpro(?:[\w.]*\w)?", re.IGNORECASE)


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


def test_an_env_file_that_still_sets_a_removed_setting_starts(tmp_path, monkeypatch) -> None:
    """T-4.11.1.4 took these four out of `Settings`, and an install's `.env` may
    still set them. `extra = "ignore"` is what keeps that install booting: with
    pydantic-settings' default of "forbid", each line stops the app at import."""
    removed = ("MAX_VIDEOS_PER_JOB", "MAX_REPORT_WORDS", "LLM_MAX_CONTEXT_TOKENS", "OAUTH_REDIRECT_BASE_URL")
    env = tmp_path / ".env"
    env.write_text("".join(f"{name}=1\n" for name in removed), encoding="utf-8")
    for name in FIELDS:
        monkeypatch.delenv(name, raising=False)
    for name in removed:
        monkeypatch.setenv(name, "1")
    loaded = Settings(_env_file=env, _env_file_encoding="utf-8")
    assert not any(hasattr(loaded, name) for name in removed)


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


def test_the_scan_finds_the_strings_it_exists_for() -> None:
    expected = {"videoresearchpro", "VideoResearchPro", "videoresearchpro.authToken",
                "videoresearchpro.authUser", "videoresearchpro.db"}
    assert expected <= _legacy_strings()


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


def test_the_runbook_says_alembic_follows_database_url() -> None:
    """T-2.6.7: env.py falls back to the setting, so section B needs no second
    edit, only a warning about a `sqlalchemy.url` line an operator added."""
    env = (ROOT / "backend" / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "settings.DATABASE_URL" in env
    text = (ROOT / "docs" / "migration-code-identifiers.md").read_text(encoding="utf-8")
    table = text[text.index("## What's renaming"):text.index("## Why these two")]
    assert "Alembic reads that file" not in table
    section_b = text[text.index("## §B"):text.index("## §C")]
    assert "sqlalchemy.url" in section_b and "alembic current" in section_b


# ── docs/ui-pages.md ─────────────────────────────────────────────────────


def _frontend_routes() -> set[str]:
    """Every path in the router. Children hang off `/`, so a bare path is under it."""
    text = (ROOT / "frontend" / "src" / "routes" / "index.tsx").read_text(encoding="utf-8")
    return {p if p == "*" else "/" + p.lstrip("/") for p in re.findall(r"\bpath: '([^']+)'", text)}


def _ui_pages() -> str:
    return (ROOT / "docs" / "ui-pages.md").read_text(encoding="utf-8")


def _route_table() -> dict[str, str]:
    """The route table: each path with the cell naming what renders it."""
    text = _ui_pages()
    section = text[text.index("## Route table"):text.index("## Page-by-page")]
    return dict(re.findall(r"^\| `([^`]+)` \| ([^|]+) \|", section, re.M))


def test_every_frontend_route_is_in_ui_pages() -> None:
    """It calls itself the single source of truth for the page inventory, and
    seven routes were missing from it, the whole of account security among them."""
    routes = _frontend_routes()
    assert len(routes) > 30, "the router did not parse"
    missing = sorted(routes - set(_route_table()))
    assert not missing, f"add to docs/ui-pages.md: {missing}"


def test_ui_pages_lists_no_route_that_does_not_exist() -> None:
    unknown = sorted(set(_route_table()) - _frontend_routes())
    assert not unknown, f"no such route: {unknown}"


def test_every_routed_page_has_a_section_in_ui_pages() -> None:
    """`OnboardingGate` only redirects, and `*` has no component."""
    sections = set(re.findall(r"^### `(\w+)`", _ui_pages(), re.M))
    pages = {name for cell in _route_table().values() for name in re.findall(r"`(\w+Page)`", cell)}
    assert len(pages) > 30
    missing = sorted(pages - sections)
    assert not missing, f"add a section to docs/ui-pages.md: {missing}"


def test_ui_pages_says_how_the_session_is_kept() -> None:
    """The key name, because a doc naming the wrong one sends a reader to rename
    a key that is not there; renaming the real ones signs every browser out."""
    source = (ROOT / "frontend" / "src" / "services" / "sessionExpiry.ts").read_text(encoding="utf-8")
    key = re.search(r"AUTH_TOKEN_KEY = '([^']+)'", source).group(1)
    assert key in _ui_pages()
    assert "pratidhvani_token" not in _ui_pages()


# ── The opening of CLAUDE.md ─────────────────────────────────────────────

#: Each directory under app/sources, and what the overview calls it.
SOURCE_NAMES = {
    "video": "YouTube",
    "podcast": "podcasts",
    "article": "articles",
    "reddit": "Reddit",
    "hn": "Hacker News",
    "mastodon": "Mastodon",
    "bluesky": "Bluesky",
    "twitter": "X threads",
    "pdf": "PDFs",
    "paste_url": "pasted pages",
}


def test_the_overview_says_which_sources_ship() -> None:
    """It is the first thing every session reads. Calling podcasts, threads and
    PDFs future work invites designing on `video_id`, which D-070 forbids."""
    shipped = {p.name for p in (ROOT / "backend" / "app" / "sources").iterdir() if (p / "__init__.py").exists()}
    assert shipped == set(SOURCE_NAMES), "name the new connector in CLAUDE.md's overview and here"
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    overview = next(x for x in text.splitlines() if x.startswith("**Pratidhvani"))
    assert "future:" not in overview
    missing = sorted(name for name in SOURCE_NAMES.values() if name not in overview)
    assert not missing, f"add to CLAUDE.md's overview: {missing}"
    assert "docs/source-types.md" in overview


# ── Tenancy ──────────────────────────────────────────────────────────────


def _tables() -> dict:
    for module in pkgutil.iter_modules(app_models.__path__):
        importlib.import_module(f"app.models.{module.name}")
    return Base.metadata.tables


def _doc(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


@pytest.mark.parametrize("path, start", [
    ("docs/requirements.md", "- **NFR-7.1.**"),
    ("docs/architecture.md", "- Most user-scoped tables carry `tenant_id`"),
    ("docs/saas-roadmap.md", "**Where the code stands.**"),
])
def test_the_tenancy_docs_name_each_table_with_no_tenant_id(path: str, start: str) -> None:
    """They said every user-scoped table has the column. A tenant-filtered read
    of `outputs` or `quota_usage` written from that would name a column that
    is not there, and those tables would miss the SaaS retrofit list."""
    tables = {name for name, t in _tables().items() if "user_id" in t.c and "tenant_id" not in t.c}
    assert {"outputs", "quota_usage", "sessions"} <= tables, "the scan found nothing"
    line = next((x for x in _doc(path).splitlines() if x.startswith(start)), "")
    missing = sorted(t for t in tables if f"`{t}`" not in line)
    assert not missing, f"{path} must name them: {missing}"


@pytest.mark.parametrize("path", ["docs/requirements.md", "docs/architecture.md"])
def test_no_doc_says_every_user_scoped_table_has_a_tenant_id(path: str) -> None:
    text = _doc(path)
    assert "Every user-scoped table has a `tenant_id` column" not in text
    assert "Every user-scoped row carries `tenant_id`," not in text


def test_the_saas_roadmap_says_the_scope_helper_is_not_built() -> None:
    """Invariant 2 describes a `with_tenant_scope` helper, and NFR-7.2 says there
    is none. The invariant can stand as a rule; the code's state goes beside it."""
    code = (ROOT / "backend" / "app").rglob("*.py")
    assert not any("with_tenant_scope" in p.read_text(encoding="utf-8") for p in code)
    note = next((x for x in _doc("docs/saas-roadmap.md").splitlines() if x.startswith("**Where the code stands.**")), "")
    assert "`with_tenant_scope`" in note


def test_contributing_gives_the_real_tenant_id_type() -> None:
    assert isinstance(_tables()["jobs"].c.tenant_id.type, String)
    assert "tenant_id INTEGER" not in _doc("docs/contributing.md")


# ── Channel sync ─────────────────────────────────────────────────────────


def test_no_doc_says_channels_sync_on_their_own() -> None:
    """Nothing schedules a channel sync: it runs when a subscription starts and
    on Sync now, so new uploads wait for someone to press it. The day a kind
    syncs channels, the first assertion fails and the docs may say so."""
    for module in ("echo_connector_tasks", "echo_tasks", "newsletter_tasks", "saved_search_tasks"):
        importlib.import_module(f"app.tasks.{module}")
    kinds = scheduler_service.registered_kinds()
    assert "saved_search" in kinds and "newsletter" in kinds, "the kinds did not register"
    assert not [k for k in kinds if "channel" in k or "subscription" in k]
    logs = {"decisions.md", "initiatives.md"}
    stale = [p.name for p in (ROOT / "docs").glob("*.md") if p.name not in logs
             and "auto-pull" in p.read_text(encoding="utf-8").lower()]
    assert not stale, f"nothing pulls on its own: {stale}"
    vision = _doc("docs/vision.md")
    assert "Sync now" in vision[vision.index("### Ring 1"):vision.index("### Ring 2")]


# ── Speak as me ──────────────────────────────────────────────────────────


def _speak_as_me() -> str:
    text = _doc("docs/personal-brain.md")
    return text[text.index("## Domain 4"):text.index("## Domain 5")]


def _fence_after(text: str, heading: str) -> str:
    return text[text.index(heading):].split("```")[1]


def test_the_speak_as_me_diagram_shows_the_graph() -> None:
    """`revise` was missing, so the diagram read as one draft and one check."""
    nodes = {n for n in echo_agent.build_graph(None).get_graph().nodes if not n.startswith("__")}
    assert {"draft", "revise", "finalize"} <= nodes
    diagram = _fence_after(_speak_as_me(), "### Pipeline")
    missing = sorted(n for n in nodes if n not in diagram)
    assert not missing, f"add to docs/personal-brain.md's diagram: {missing}"
    assert "self_critique_against_voice → revise → self_critique_against_voice" in diagram


def test_the_speak_as_me_steps_name_real_stores() -> None:
    section = _speak_as_me()
    assert "videoresearchpro_global" not in section
    assert FIELDS["CHROMA_GLOBAL_COLLECTION_NAME"].default in section
    assert "personal_facts" not in section
    assert "`personal_context`" in section
    assert "ECHO_DRAFT_CRITIQUE_ROUNDS" in section and "0-10" not in section


def test_the_speak_as_me_output_contract_is_what_finalize_returns() -> None:
    source = (ROOT / "backend" / "app" / "agents" / "echo_agent.py").read_text(encoding="utf-8")
    result = source[source.index('"result": {'):source.index("g = StateGraph(DraftState)")]
    returned = set(re.findall(r'^ +"(\w+)":', result, re.M)) - {"result"}
    assert {"draft", "citations", "voice_match_score"} <= returned
    contract = json.loads(_fence_after(_speak_as_me(), "### Output contract").removeprefix("json"))
    assert set(contract) == returned
    assert 20 <= contract["voice_match_score"] <= 100, "finalize scales 1-5 to a percentage"
    assert isinstance(contract["deviation_notes"], list)
    assert all({"kind", "ref", "label"} <= set(c) for c in contract["citations"])


def test_personal_brain_says_what_the_facts_table_is() -> None:
    """Its header promises an "as built" note wherever the shipped shape differs."""
    assert "personal_context" in _tables()
    text = _doc("docs/personal-brain.md")
    domain = text[text.index("## Domain 1"):text.index("## Domain 2")]
    assert "**As built" in domain and "`personal_context`" in domain
    assert "personal_facts" not in _doc("docs/feature-roadmap.md")


# ── docs/testing.md ──────────────────────────────────────────────────────


def _ci() -> str:
    return _doc(".github/workflows/ci.yml")


def _test_count() -> str:
    return re.search(r"All backend tests \(([\d,]+\+)", _doc("CLAUDE.md")).group(1)


@pytest.mark.parametrize("path", ["README.md", "docs/architecture.md", "docs/contributing.md", "docs/testing.md"])
def test_every_doc_gives_the_same_test_count(path: str) -> None:
    """docs/testing.md said 1013 long after the suite passed 4,000."""
    assert _test_count() in _doc(path)


def test_the_test_count_is_what_the_suite_collects(request) -> None:
    floor = int(_test_count().rstrip("+").replace(",", ""))
    collected = len(request.session.items)
    if collected < floor * 0.9:
        pytest.skip("a partial run: the count is read on a full one")
    assert floor <= collected < floor + 500, (
        f"{collected} tests: update {_test_count()} in CLAUDE.md, the README, architecture, contributing and testing"
    )


def test_the_testing_doc_gives_the_suite_its_real_speed() -> None:
    """A reader told "seconds" takes a 20-minute run for a hung one."""
    text = _doc("docs/testing.md")
    for stale in ("seconds, not minutes", "well under a minute", "(a) through (d) takes seconds"):
        assert stale not in text
    assert "about 20 minutes" in text[text.index("## 1. Goals"):text.index("## 2. Layout")]


def test_the_testing_doc_counts_the_device_suite_as_shipped() -> None:
    """It called Playwright future work while CI's device job gated every PR."""
    assert "npm run test:mobile" in _ci()
    text = _doc("docs/testing.md")
    non_goals = text[text.index("**Non-goals.**"):text.index("## 2. Layout")]
    assert "Out of scope today" not in non_goals
    assert "#56-frontend-suites" in non_goals and "Load tests" in non_goals


def test_the_testing_doc_says_what_gates_the_frontend() -> None:
    assert "eslint" not in _ci().lower() and "npm run lint" not in _ci()
    assert "plus ESLint" not in _doc("docs/testing.md")


def test_the_testing_doc_says_a_run_spends_nothing() -> None:
    """conftest.py has stubbed the probes since 2026-10-19, and a reader told a
    run costs a few cents batches reruns for no reason."""
    assert 'patch("app.main.run_startup_probes"' in _doc("backend/tests/conftest.py")
    assert "a few cents" not in _doc("docs/testing.md")


# ── The README ───────────────────────────────────────────────────────────


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_readme_gives_the_real_collection_default() -> None:
    assert "videoresearchpro_global" not in _readme()
    assert FIELDS["CHROMA_GLOBAL_COLLECTION_NAME"].default in _readme()


def test_the_readme_has_no_stale_test_count() -> None:
    line = next(x for x in _readme().splitlines() if "pytest tests" in x)
    assert _test_count() in line


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


def test_the_usage_example_shows_every_amount_the_response_carries() -> None:
    """`UsageAmounts` defaults each field to 0, so validating the example would
    pass with one missing. An API client is built from the example's keys."""
    text = _reference()
    section = text[text.index("### `GET /api/v1/usage`"):]
    start = section.index("```json") + len("```json")
    example = json.loads(section[start:section.index("```", start)])
    rows = [*example["features"], example["totals"]]
    assert all(set(row[w]) == set(UsageAmounts.model_fields) for row in rows for w in ("today", "last_30_days"))


def test_architecture_states_the_knowledge_excerpt_setting_as_it_is() -> None:
    """T-4.11.2.6: the setting is the excerpt's size, with no literal cap above it.
    An operator sizes it from this line, and the checks above do not read prose."""
    text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    line = next(row for row in text.splitlines() if row.startswith("- **split_transcript**"))
    assert f"(default {FIELDS['KNOWLEDGE_MAX_TRANSCRIPT_TOKENS'].default:,})" in line
    assert "never above" not in line


def test_the_reference_does_not_claim_no_doc_lists_endpoints() -> None:
    """CLAUDE.md lists every route, and the tests above hold it to the app."""
    assert "rather than duplicating endpoint lists" not in _reference()
