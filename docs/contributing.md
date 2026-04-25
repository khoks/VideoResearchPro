# Contributing to Pratidhvani (प्रतिध्वनि)

> Status: living doc (last refreshed 2026-04-24). Owns: setup, day-to-day commands, code style, PR checklist, commit conventions. Testing strategy lives in [docs/testing.md](testing.md).

This guide gets you from a fresh clone to a green PR. If anything here drifts from reality, fix the doc in the same PR — stale setup instructions are worse than missing ones.

---

## 1. First-time setup (Windows)

The project is developed on Windows but is platform-portable. Linux/macOS notes appear inline where commands diverge.

### 1.1. Prerequisites

| Tool | Version | Why |
|------|---------|-----|
| Python | 3.12+ | FastAPI / Celery / LangGraph |
| Node.js | 20+ | Frontend (Vite 8, React 19) |
| Redis | 7+ | Celery broker, results, pub/sub |
| Git | any | source control |

### 1.2. Redis

```powershell
winget install Redis.Redis      # installs and starts as a Windows service on :6379
redis-cli ping                  # → PONG
```

On Linux/macOS use the distro package or `brew install redis` and `brew services start redis`.

### 1.3. Backend

```bash
cd backend
python -m venv venv
./venv/Scripts/pip install -r requirements.txt
./venv/Scripts/pip install -r requirements-dev.txt
cp ../.env.example .env         # then fill in YOUTUBE_API_KEY + at least one LLM provider key
./venv/Scripts/alembic upgrade head
```

**Always use the venv.** Never `pip install` into the system Python — the project relies on `./venv/Scripts/python` (Windows) / `./venv/bin/python` (Linux) being the canonical interpreter for backend tooling.

### 1.4. Frontend

```bash
cd frontend
npm install
```

### 1.5. `.env` essentials

Copy `.env.example` to `backend/.env`. Minimum viable config:

```
YOUTUBE_API_KEY=...           # required
OPENAI_API_KEY=...            # required out of the box (default use-case routing)
JWT_SECRET=...                # any long random string
DATABASE_URL=sqlite:///./data/videoresearchpro.db
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
```

If you swap a use case to Anthropic / Google / local via `LLM_USE_CASE_CONFIG`, add the matching credential. See [CLAUDE.md](../CLAUDE.md#llm-configuration) for the full table.

---

## 2. Day-to-day commands

Three terminals are usually open: API, worker, frontend.

### 2.1. API server

```bash
cd backend
./venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

### 2.2. Celery worker

```bash
cd backend
./venv/Scripts/celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
```

`--pool=solo` is mandatory on Windows. On Linux you can drop it (default `prefork` works).

### 2.3. Frontend

```bash
cd frontend
npm run dev                    # http://localhost:5173
```

### 2.4. Tests, lint, type-check

```bash
# Backend tests (168 of them)
cd backend && ./venv/Scripts/python -m pytest tests/ -v

# Backend lint
cd backend && ./venv/Scripts/ruff check .

# Frontend type check + production build
cd frontend && npm run build

# Frontend lint
cd frontend && npm run lint
```

Runbook for stress-testing LLM configs lives in [CLAUDE.md](../CLAUDE.md#llm-stress-testing).

---

## 3. Database migrations (Alembic)

Schema changes go through Alembic. The backend ships with a linear migration history under `backend/alembic/versions/`.

```bash
cd backend
./venv/Scripts/alembic revision -m "add_foo_to_bar"     # create empty revision
./venv/Scripts/alembic upgrade head                      # apply pending
./venv/Scripts/alembic downgrade -1                      # roll back one
./venv/Scripts/alembic history                           # see chain
```

**Conventions:**

- Filename: `<rev>_<snake_case_summary>.py`. Pick a fresh hex prefix; don't reuse one.
- Every revision must define `upgrade()` **and** `downgrade()`. `downgrade()` may `raise NotImplementedError` for destructive changes, but never leave it empty.
- Add new tables and columns with `tenant_id INTEGER NOT NULL` (or a TODO comment + migration ticket). Forward-compat with multi-tenancy is non-negotiable — see [docs/saas-roadmap.md](saas-roadmap.md).
- Index any column you'll filter on. Especially `tenant_id`, `user_id`, `created_at`.
- Don't drop columns inline with a feature change; do it in a follow-up migration after one release of soft-deprecation.

---

## 4. Code style

### 4.1. Python (backend)

- **Formatter / linter:** `ruff` (config in `backend/pyproject.toml` if present, else defaults). Run `./venv/Scripts/ruff check .` before committing.
- **Type hints:** required on every public function and every method on a service / router / agent. Internal helpers can elide them when types are obvious.
- **Imports:** isort-compatible order — stdlib, third-party, local. `ruff` enforces this.
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes, `SCREAMING_SNAKE` for module constants.
- **Async:** routers and Celery task entrypoints can be async; service-layer functions are sync (Celery workers are sync). When a service needs to call an async lib, wrap with `asyncio.run` or use a thread executor — but prefer adding a sync overload.
- **Logging:** use the module logger (`logger = logging.getLogger(__name__)`). Never `print()` outside `scripts/`.
- **No dead code:** don't leave commented-out blocks, `_unused` variables, or "for future use" stubs. Delete; it's in git.

### 4.2. TypeScript (frontend)

- **Compiler:** `tsc -b` (run by `npm run build`) is the gate. PRs must build.
- **Linter:** ESLint via `npm run lint`. Existing rules are in `eslint.config.js` (root of `frontend/`).
- **Inline styles:** the project uses inline `style={{}}` objects, **not** CSS modules or styled-components. New code must follow suit.
  - Pull values from `frontend/src/theme.ts` (token system) — see [docs/ui-design.md](ui-design.md).
  - Don't sprinkle hard-coded hex colors. If you need a token, add it to `theme.ts` and reference it.
- **State:** server state via TanStack Query, UI state via Zustand. Don't introduce a third state library.
- **Types over `any`:** `any` in production code blocks PR review. Test fixtures may use it.
- **File names:** `PascalCase.tsx` for components, `camelCase.ts` for everything else.

### 4.3. Cross-cutting

- **No emojis in code or docs** unless the user explicitly asks for them.
- **No comments that restate code.** Reserve comments for the *why* — invariants, surprises, hidden constraints.
- **No backwards-compat shims** for code that hasn't shipped to users yet. If you renamed a function inside the same PR, just rename — don't leave the old name as an alias.

---

## 5. PR checklist

Every PR ticks these before review.

### 5.1. Mechanical

- [ ] `ruff check .` clean (backend)
- [ ] `pytest tests/ -v` green (backend)
- [ ] `npm run build` green (frontend) — this includes `tsc -b`
- [ ] `npm run lint` green (frontend)
- [ ] Alembic migration added if any model changed; both `upgrade()` and `downgrade()` implemented
- [ ] `.env.example` updated if any new env var was introduced

### 5.2. Substance

- [ ] **Forward-compat audit.** New tables / columns include `tenant_id` (or a tracked TODO). New endpoints scope by `current_user`. New LLM call sites are registered as a use case in `app/services/llm_routing.py::USE_CASE_REGISTRY`. See [docs/saas-roadmap.md §PR-checklist](saas-roadmap.md).
- [ ] **Brand coherence.** No new mention of `VideoResearchPro` user-facing — that's a legacy name. Use `Pratidhvani` / `प्रतिध्वनि` per [docs/branding.md](branding.md). Internal env var names like `CHROMA_GLOBAL_COLLECTION_NAME=videoresearchpro_global` are grandfathered.
- [ ] **Doc updates landed in the same PR.** If you changed an endpoint, update [docs/api-reference.md](api-reference.md). If you added a page, update [docs/ui-pages.md](ui-pages.md). If you introduced a major feature, update [docs/feature-roadmap.md](feature-roadmap.md) status.
- [ ] **No new features behind silent flags.** Either it's user-facing or it's not in the PR.
- [ ] **No drive-by refactors.** A bug-fix PR doesn't reformat unrelated files.

### 5.3. UI changes specifically

- [ ] Tested in light mode AND dark mode.
- [ ] Tested at 640px (mobile) AND 1280px (desktop).
- [ ] Visible focus rings on every interactive element. Don't `outline: none` without replacing it.
- [ ] Empty / loading / error states all designed (not just default state).
- [ ] Reading content uses serif body, UI chrome uses sans. Don't mix.
- [ ] Verified by running the dev server in a browser, not just by passing type-check. Type-check is a code correctness gate, not a feature correctness gate.

---

## 6. Commit & PR conventions

### 6.1. Commit message style

We loosely follow Conventional Commits but enforce only the prefix.

```
feat(scope): short imperative summary

(optional body — what changed and why; wrapped at 80 cols)

(optional footer — Closes #123, Co-Authored-By, etc.)
```

Allowed prefixes: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`, `perf`, `build`, `ci`, `revert`.

`scope` is the area of change: `backend`, `frontend`, `agents`, `auth`, `chroma`, `qa`, `library`, `channels`, `knowledge`, `exports`, `docs`, etc.

Examples (from real history):

```
feat(qa): add per-use-case LLM config + smoke-check + fail-soft UI
fix(qa-history): retrieve from qa_library_global instead of per-job collection
refactor(routing): consolidate LLM routing registry
docs(branding): rename VideoResearchPro → Pratidhvani
```

### 6.2. PR title

Same shape as the commit subject. Title under 70 chars. If you need more, that's what the body is for.

### 6.3. PR body

Minimum:

```markdown
## Summary
- one-line bullet per significant change

## Test plan
- [ ] manual / automated steps you ran
```

For larger PRs, also add:

- **Screenshots** (UI changes) — light + dark.
- **Migration notes** (schema changes) — what the migration does and how to roll back.
- **Forward-compat impact** (anything touching auth, tenancy, billing-relevant fields).

### 6.4. Don'ts

- **Don't** force-push to `master`.
- **Don't** skip pre-commit hooks (`--no-verify`). If a hook fails, fix the cause.
- **Don't** amend a published commit. Make a follow-up commit.
- **Don't** commit `.env`, `data/`, `__pycache__/`, `node_modules/`, generated reports under `outputs/`, or anything in `backend/data/chroma/`. The `.gitignore` covers the obvious cases — if your editor adds something else, add a rule.

---

## 7. Where to look when you're stuck

| Question | Doc |
|----------|-----|
| Why does this product exist? | [docs/vision.md](vision.md) |
| What's the architecture? | [docs/architecture.md](architecture.md) |
| What endpoints exist? | [docs/api-reference.md](api-reference.md) |
| What pages exist? | [docs/ui-pages.md](ui-pages.md) |
| What features are planned? | [docs/feature-roadmap.md](feature-roadmap.md) |
| How is testing set up? | [docs/testing.md](testing.md) |
| What's the visual language? | [docs/ui-design.md](ui-design.md) and [docs/branding.md](branding.md) |
| How do LLM use cases work? | [CLAUDE.md §LLM configuration](../CLAUDE.md#llm-configuration) |
| What's the SaaS plan? | [docs/saas-roadmap.md](saas-roadmap.md) |

If you're a Claude Code session, [CLAUDE.md](../CLAUDE.md) is always loaded — start there.

---

## 8. Reporting issues

- **Bugs:** open a GitHub issue with: repro steps, expected vs actual, log output (last 50 lines from API + worker), browser/OS.
- **Security disclosures:** email the maintainer directly; do not file a public issue.
- **Feature ideas:** open a discussion thread, not an issue. If accepted, it'll graduate into [docs/feature-roadmap.md](feature-roadmap.md).
