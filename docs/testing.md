# Testing

> Status: living doc (last refreshed 2026-05-05). Owns: testing strategy, fixture catalogue, how to add a test, how to run the LLM stress harness. Setup commands live in [docs/contributing.md](contributing.md).

The backend ships with **1013 tests** under `backend/tests/`. The frontend gates on `tsc -b` plus ESLint; no Jest / Vitest suite yet (see [open work](#7-open-work)). This doc explains the conventions so a new contributor can add a test in five minutes.

---

## 1. Goals & non-goals

**Goals.**

- **Fast.** Full backend suite runs in seconds, not minutes. No real Redis, no real Postgres, no real LLM calls, no real YouTube API.
- **Hermetic.** A test never depends on another test's state, the network, or the developer's machine. CI parity == local parity.
- **Honest about boundaries.** Mocks at the *system edges* (Celery dispatch, ChromaDB persistence, LLM clients, YouTube API). Code on the inside of those edges runs for real.

**Non-goals.**

- Browser end-to-end tests. Out of scope today; the design intent is to introduce Playwright once the warm-editorial UI redesign lands and pages stabilize. Until then, UI changes are verified by running the dev server in a browser (see [docs/contributing.md §5.3](contributing.md#53-ui-changes-specifically)).
- Load tests against live infrastructure. Use the LLM stress harness for capacity planning of the model layer; everything else is small enough that micro-benchmarks would mislead more than help.

---

## 2. Layout

```
backend/tests/
├── conftest.py                 # fixtures: db, client, auth_headers, seeded_global_library
├── test_routers/               # HTTP-level tests (auth, jobs, qa, library, channels, ...)
├── test_services/              # service-layer tests (chroma, embedding, llm_routing, ...)
├── test_agents/                # LangGraph agent tests (search, report, qa, knowledge, ...)
├── test_tasks/                 # Celery task body tests (subscription_task, upsert_dedup)
├── test_models/                # SQLAlchemy model tests
├── test_utils/                 # pure-function tests (chunking, youtube_helpers)
└── test_smoke/                 # cross-feature integration smoke (added 2026-05-05)
```

The directory mirrors `backend/app/`. New code under `app/foo/` gets new tests under `tests/test_foo/`. Don't bury tests inside `app/` — keep the source tree clean.

`test_smoke/` is the **integration-level** layer: it walks complete user journeys across multiple surfaces (e.g. register → login → MFA → BYOK → echo → author → quota → logout) and asserts cross-feature integrations work. The unit/integration suites under `test_routers/` etc. each cover one surface in depth; the smoke layer catches regressions that only show up when surfaces compose. Smoke tests use the same fixtures (`db`, `client`, `unauthenticated_client`) as everything else — no extra infra; the difference is breadth, not stack.

### When to add a smoke test

- A new feature that touches **multiple existing surfaces** (e.g. a quota-bearing endpoint that also writes audit log + records metering + dispatches Celery).
- A **cross-tenant isolation** invariant — two users active simultaneously, neither sees the other's data through any surface.
- A **status-machine flow** that crosses async boundaries (e.g. login → MFA second-step → session list → logout-revokes-current).

For single-surface bugs, write a regular `test_routers/` or `test_services/` test — smoke is for the integration story.

---

## 3. The five test isolation tricks

Four are substitutions for external systems. The fifth (3.5) is about global
process state that no fixture owns.

### 3.1. Database: in-memory SQLite with `StaticPool`

`conftest.py:14-21` builds an in-memory engine shared across the connection pool. The `db` fixture creates all tables on entry and drops them on exit — every test gets a clean schema.

```python
SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
```

`StaticPool` is the magic — without it, in-memory SQLite would give every connection a fresh empty database.

The router-level `client` fixture overrides `get_db` so FastAPI handlers see this session. No real Postgres, no Alembic, no migrations.

### 3.2. Celery: `.delay()` mocked at the router boundary

Real Celery would require Redis. We don't want that in unit tests. `conftest.py:66-77` patches the four task functions where the routers import them:

```python
with (
    patch("app.routers.jobs.execute_topic_job") as mock_topic,
    patch("app.routers.jobs.execute_channel_job") as mock_channel,
    patch("app.routers.jobs.execute_subscription_job") as mock_subscription,
    patch("app.routers.jobs.resume_job_after_approval") as mock_resume,
):
    mock_topic.delay.return_value = MagicMock(id="mock-topic-task-id")
    ...
```

**Why patch at the router and not the task module?** Because `from app.tasks.job_tasks import execute_topic_job` binds the name `execute_topic_job` *inside `app.routers.jobs`*. Patching the original would miss this binding.

Tests for the **task body itself** (under `tests/test_tasks/`) call the function directly with a real db session and mock the inner side-effects (YouTube API, Chroma client) instead.

### 3.3. ChromaDB: `EphemeralClient` + monkeypatch

`PersistentClient` writes to disk under `backend/data/chroma/`. Tests use `EphemeralClient`, which lives entirely in memory:

```python
import chromadb
from app.services import chroma_service

@pytest.fixture
def ephemeral_chroma(monkeypatch):
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield client
    monkeypatch.setattr(chroma_service, "_client", None)
```

The `_client` module-level variable is the singleton; patching it at import time before `chroma_service.get_collection()` is called swaps the implementation seamlessly.

For tests that need to wipe state mid-test, pass `ChromaSettings(allow_reset=True)` and call `client.reset()` between phases — see `tests/test_services/test_library_chroma.py` for the pattern.

### 3.4. LLM clients: factory-level patching

Every LLM call resolves through `app.services.llm_routing.get_llm(use_case)` which returns a `langchain_*` chat model. Tests patch the factory or the model's `.invoke()` / `.ainvoke()` method.

```python
def test_qa_agent_handles_empty_context(monkeypatch):
    fake = MagicMock()
    fake.invoke.return_value = MagicMock(content="No relevant context found.")
    monkeypatch.setattr("app.agents.qa_agent.get_llm", lambda use_case: fake)
    ...
```

Real provider SDKs are never instantiated in tests. The `LLM_USE_CASE_CONFIG` env var is also irrelevant — patches short-circuit it.

For testing the **routing logic itself** (provider selection, env parsing, fail-soft probing), see `tests/test_services/test_llm_routing.py`, `test_llm_service_routing.py`, and `test_llm_smoke.py`.

---

### 3.5. Logging: assert on the logger, not on `caplog`

`caplog` is a fixture over **global** logging state. A record only reaches it
if nothing else in the process has disabled logging, replaced the root
handler list, or cut propagation on an ancestor logger. Nothing guarantees
that across a 1,300-test suite, and nothing warns you when it stops being
true — the assertion just silently starts measuring the wrong thing.

This is not hypothetical. `test_exhaustion_is_announced_once_not_per_video`
(R1 frame budget) passed on its own, passed after `test_agents`,
`test_models`, `test_routers` and `test_utils`, and failed in the full suite
with `assert 0 == 1` — zero records captured — once `test_services` had run
first. The code under test was emitting the warning correctly the whole time.

**The root cause turned out to be a production bug, not a test problem.**
`alembic/env.py` calls `fileConfig(...)`, whose `disable_existing_loggers`
argument defaults to `True`: it sets `.disabled` on every logger not named
in `alembic.ini`, which is all of `app.*`. `test_schema_init.py` runs real
migrations in-process, so every `caplog` test after it saw nothing — and so
did `app/main.py`'s startup path, which migrates in-process on a fresh
install and then silently lost its entire application log for the life of
the process, starting with the very `logger.info(f"schema_init: {result}")`
that reports the migration. A standalone `alembic upgrade` is unaffected,
which is why it went unnoticed. Fixed by passing
`disable_existing_loggers=False`; pinned by
`test_startup_migration_does_not_disable_app_loggers`.

A disabled logger is worth recognising on sight: it reports
`propagate=True` and a sane effective level and drops records anyway, so
every obvious diagnostic looks healthy. Check `logger.disabled` and
`logger.isEnabledFor(level)` early.

**When the claim is "this code logs X", patch the logger:**

```python
def test_exhaustion_is_announced_once_not_per_video():
    budget = VisualBudget(0)
    with patch("app.tasks.job_tasks.logger") as log:
        for _ in range(5):
            _with_visuals(None, job, video, segments, budget, "j1")

    warnings = [c for c in log.warning.call_args_list
                if "budget exhausted" in str(c.args[0])]
    assert len(warnings) == 1
```

This is stricter than the `caplog` form, not weaker: it pins *which* logger
emitted, *how many times*, and is immune to whatever ran before it.

`caplog` is still fine when the log line genuinely is the observable — e.g.
`test_email_service.py` asserting that an unconfigured-SMTP fallback prints
the body it would have sent. The rule is about which thing you are claiming:
**behaviour of your function → patch the logger; content of a log-as-output
surface → `caplog` is the subject.**

---

## 4. Fixture catalogue

All fixtures live in `backend/tests/conftest.py`. They're stacked — most tests just take `client` and inherit the rest transitively.

| Fixture | Provides | Use it when |
|---------|----------|-------------|
| `db` | A `Session` bound to in-memory SQLite, schema fresh per test. | You need direct ORM access to insert/inspect rows. |
| `test_user` | A persisted `User` row (`test@example.com`). | Most tests touch user-scoped data. |
| `auth_token` | A JWT for `test_user`. | When you need to assert auth flows manually. |
| `auth_headers` | `{"Authorization": "Bearer ..."}`. | When you call the FastAPI client without going through `client`. |
| `client` | `TestClient` with auth headers attached and Celery mocked. | The default for router tests. |
| `unauthenticated_client` | Same as `client` but no auth headers. | Testing 401 / unauth-allowed endpoints. |
| `seeded_global_library` | 5 videos × 2 channels in `videos` / `channels`. | Library or job-creation tests that need pre-existing rows. |

Add a fixture by editing `conftest.py`. If a fixture is only used by one file, define it there instead — `conftest.py` is for cross-file reuse.

---

## 5. Running the suite

### 5.1. Full suite

```bash
cd backend
./venv/Scripts/python -m pytest tests/ -v
```

Expect green in well under a minute on a typical dev machine.

### 5.2. One file or one test

```bash
./venv/Scripts/python -m pytest tests/test_routers/test_jobs.py -v
./venv/Scripts/python -m pytest tests/test_routers/test_jobs.py::test_create_topic_job -v
```

### 5.3. With coverage (optional, not gated)

```bash
./venv/Scripts/python -m pytest tests/ --cov=app --cov-report=term-missing
```

Coverage is informational — there is no enforced floor. Prefer adding tests where bugs would actually hurt (auth, billing-relevant code, agent state machines) over chasing a number.

### 5.4. CI

CI runs the same `pytest tests/ -v` plus `ruff check .` and the frontend build. PRs that fail any of these are blocked.

### 5.5. Pre-merge sanity checks (manual)

For risky PRs (schema migrations, cross-cutting refactors, anything touching `app/main.py` boot path), run these manually before merging:

```bash
# (a) Full suite — already covered above.
./venv/Scripts/python -m pytest tests/ -q

# (b) Migration round-trip — every migration's downgrade() works.
./venv/Scripts/python -c "
import os
fresh = os.path.abspath('./data/_test_revertable.db')
if os.path.exists(fresh): os.unlink(fresh)
from alembic import command
from alembic.config import Config
cfg = Config('alembic.ini')
cfg.set_main_option('sqlalchemy.url', f'sqlite:///{fresh}')
command.upgrade(cfg, 'head')
command.downgrade(cfg, 'base')
command.upgrade(cfg, 'head')
os.unlink(fresh)
print('migration round-trip: OK')
"

# (c) ORM ↔ migrations parity — Base.metadata matches the migrated DB.
./venv/Scripts/python -c "
import os
fresh = os.path.abspath('./data/_test_parity.db')
if os.path.exists(fresh): os.unlink(fresh)
from alembic import command
from alembic.config import Config
cfg = Config('alembic.ini'); cfg.set_main_option('sqlalchemy.url', f'sqlite:///{fresh}')
command.upgrade(cfg, 'head')
from sqlalchemy import create_engine, MetaData
from app.database import Base
from app.models import *  # noqa
engine = create_engine(f'sqlite:///{fresh}')
db_meta = MetaData(); db_meta.reflect(bind=engine)
orm = set(Base.metadata.tables.keys())
db = set(db_meta.tables.keys()) - {'alembic_version'}
print('ORM-only:', orm - db)
print('DB-only:', db - orm)
print('parity:', 'OK' if orm == db else 'MISMATCH')
"

# (d) Boot verification — TestClient lifespan + every representative route.
./venv/Scripts/python -c "
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    r = c.get('/api/v1/health')
    assert r.status_code == 200, r.status_code
    print('boot: OK; status:', r.json().get('status'))
"
```

Each of (a) through (d) takes seconds. Run all four when shipping schema changes; (a) alone for everything else.

---

## 6. Patterns: how to add a test

### 6.1. Adding a router test

Most of the codebase falls here. Use the `client` fixture; it handles auth, db override, and Celery mocking.

```python
def test_create_topic_job(client, db):
    response = client.post(
        "/api/v1/jobs",
        json={
            "type": "topic",
            "topic": "tariffs and trade policy",
            "search_instructions": "focus on independent commentary",
            "max_videos": 10,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["type"] == "topic"

    # Verify side effects in the db
    job = db.query(Job).filter_by(id=body["id"]).one()
    assert job.user_id == 1   # the test_user
```

### 6.2. Adding a service test with Chroma

```python
def test_upsert_chunks_dedupes_by_id(ephemeral_chroma, db):
    chroma_service.upsert_chunks([
        {"id": "v1::0", "text": "hello", "metadata": {"video_id": "v1"}},
        {"id": "v1::0", "text": "hello (again)", "metadata": {"video_id": "v1"}},
    ])
    coll = chroma_service.get_collection()
    assert coll.count() == 1
```

### 6.3. Adding an agent test

Patch `get_llm` to return a deterministic mock:

```python
def test_search_agent_uses_planned_queries(monkeypatch, db):
    fake = MagicMock()
    fake.invoke.side_effect = [
        MagicMock(content='["query A", "query B"]'),     # plan
        MagicMock(content='[{"video_id": "abc"}]'),       # rank
    ]
    monkeypatch.setattr("app.agents.search_agent.get_llm", lambda uc: fake)
    monkeypatch.setattr(
        "app.agents.search_agent.youtube_service.search_videos",
        lambda q, max_results: [{"video_id": "abc", "title": "..."}],
    )
    result = search_agent.run(topic="tariffs", search_instructions="...")
    assert result["videos"][0]["video_id"] == "abc"
```

### 6.4. Asserting on Celery dispatch

Because the four task functions are mocked, a router test can assert the right one was called:

```python
def test_topic_job_dispatches_topic_task(client):
    from app.routers.jobs import execute_topic_job
    response = client.post("/api/v1/jobs", json={"type": "topic", ...})
    assert response.status_code == 201
    execute_topic_job.delay.assert_called_once()
    args, kwargs = execute_topic_job.delay.call_args
    assert kwargs["job_id"] == response.json()["id"]
```

### 6.5. Testing async code

`pytest-asyncio` is installed. Mark coroutines with `@pytest.mark.asyncio`:

```python
import pytest

@pytest.mark.asyncio
async def test_websocket_subscribe(client):
    with client.websocket_connect("/ws/jobs") as ws:
        ws.send_json({"action": "subscribe", "job_id": 1})
        message = ws.receive_json()
        assert message["type"] == "subscribed"
```

---

## 7. LLM stress testing

`backend/scripts/stress_test_llm.py` is the canonical harness for **measuring** an LLM config — not a unit test, but the right tool when you're picking a model or a concurrency level.

Two ways to invoke:

```bash
cd backend

# Use a registered use case (reads provider/model/reasoning from USE_CASE_REGISTRY)
./venv/Scripts/python scripts/stress_test_llm.py --use-case qa_formulate_answer

# Ad-hoc combination — useful before committing to LLM_USE_CASE_CONFIG
./venv/Scripts/python scripts/stress_test_llm.py \
    --provider local --model qwen/qwen3-9b --concurrency 1 2 4 8
```

The harness reports p50 / p95 / max latency, single-request throughput, and aggregate throughput across the concurrency sweep. `stress_test_local_llm.py` is a thin shim that delegates here.

What it doesn't do:

- It does **not** validate correctness of responses — only timing.
- It does **not** know about your real prompts. The probe prompt is short and uniform.

For prompt-quality regression, the right tool is a small fixture suite under `tests/test_agents/` with known-good outputs, not the stress harness.

---

## 7. Open work

These gaps are tracked but not blocking day-to-day development:

- **Frontend test harness.** No Vitest / RTL setup yet. When the warm-editorial redesign stabilizes the page surfaces, introduce Vitest + Testing Library + a small Playwright suite for the Q&A flow and the approval flow. See [docs/feature-roadmap.md](feature-roadmap.md).
- **Property-based tests.** Chunking (`app/utils/chunking.py`) and timestamp-mapping logic would benefit from Hypothesis. Currently example-based.
- **End-to-end with real Redis + Celery.** The `--pool=solo` Windows constraint complicates this; revisit once SaaS infra moves to Linux containers.
- **Real-LLM smoke runs in CI.** Today the `run_startup_probes` logic is unit-tested with mocks. A nightly job that probes the real configured providers (with a tiny budget) would catch credential rotation and SDK breakage early. Tracked in [docs/saas-roadmap.md](saas-roadmap.md).

---

## 8. When tests fail

A failing test is information. Don't:

- Mark it `@pytest.mark.skip` to make CI green.
- Loosen an assertion until it passes.
- Wrap the call in `try / except: pass`.

Do:

- Read the assertion. Decide whether the test or the code expresses the intended behavior.
- If the code is right and the test was wrong, update the test in the same PR — and explain why in the commit body.
- If the test is right and the code is wrong, fix the code.
- If you genuinely can't tell, ask before merging. A skipped test is invisible; a question is loud.
