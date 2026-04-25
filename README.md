# प्रतिध्वनि · Pratidhvani

> *Your sources, echoed back.*

**Pratidhvani** (Sanskrit: "echo") is a personal curated research wiki. Unlike Wikipedia — moderated, balanced, diluted — Pratidhvani embraces **the sources you choose**: independent podcasters, niche creators, forum threads, books, articles. The curation system is the product.

It is:

- **A personal library** that grows every time you run a research job.
- **A question-answering engine** grounded in your library — every answer cites the exact video, timestamp, or past exchange it came from.
- **A knowledge-capture system**: every Q&A you've ever asked, every transcript you've ever ingested, and every structured knowledge artifact you've ever generated is searchable forever.
- **A fine-tune pipeline**: the library streams out as training-ready JSONL so you can carry your wiki as parametric knowledge inside a custom LLM.

The long-term aspiration is a **personal brain** — a system that learns your voice, your opinions, your interests, and your life so it can speak on your behalf. See [docs/vision.md](docs/vision.md) and [docs/personal-brain.md](docs/personal-brain.md).

> **Historical note.** This project was previously named *VideoResearchPro*. The legacy name survives in grandfathered environment-variable names (e.g. `CHROMA_GLOBAL_COLLECTION_NAME=videoresearchpro_global`) for back-compat, but all user-facing and documentation references are now Pratidhvani.

---

## Documentation

| I want to... | Read |
|--------------|------|
| Understand why this product exists | [docs/vision.md](docs/vision.md) |
| See the feature roadmap | [docs/feature-roadmap.md](docs/feature-roadmap.md) |
| See the visual identity | [docs/branding.md](docs/branding.md) |
| Understand the architecture | [docs/architecture.md](docs/architecture.md) |
| Look up an API endpoint | [docs/api-reference.md](docs/api-reference.md) |
| Look up a UI page | [docs/ui-pages.md](docs/ui-pages.md) |
| See functional & non-functional requirements | [docs/requirements.md](docs/requirements.md) |
| Set up a dev environment | [docs/contributing.md](docs/contributing.md) |
| Write a test | [docs/testing.md](docs/testing.md) |
| Plan for the multi-source future | [docs/source-types.md](docs/source-types.md) |
| Plan for the SaaS future | [docs/saas-roadmap.md](docs/saas-roadmap.md) |
| Plan for the personal-brain future | [docs/personal-brain.md](docs/personal-brain.md) |
| See what shipped recently | [CHANGELOG.md](CHANGELOG.md) |

---

## Features (today)

- **Topic research.** Describe a topic; an LLM-driven Search Agent finds, ranks, and curates YouTube videos, with optional preferred-channel filtering.
- **Channel research.** Paste channel URLs; pull the latest N videos per channel.
- **Channel subscriptions.** Subscribe once; every current and future video is ingested and indexed automatically. No per-job report — pure library ingestion.
- **Global video library.** One canonical copy of every transcribed video, reused across every job that references it.
- **Per-job Q&A.** Ask questions scoped to a single job's approved videos.
- **Library-wide Q&A.** Ask questions across every transcribed video in your library at once.
- **Q&A History chat.** A dedicated `/qa-history` page that searches every past Q&A exchange you've ever had and synthesizes meta-answers.
- **Per-video knowledge reports.** An on-demand map-reduce agent extracts structured `{topics, concepts, events, facts}` from any transcript and writes a Wikipedia-paragraph-style Markdown document, persisted on the video row.
- **Dataset exports.** Four streaming JSONL endpoints turn your accumulated Q&A and knowledge artifacts into training-ready datasets (OpenAI chat format and plain tuple format).
- **Multilingual.** Whisper transcribes speakers in their native language(s), including code-mixed audio. Answers respond in your chosen language while preserving proper nouns.
- **Citation-grounded.** Every answer includes clickable YouTube timestamps and links back to source exchanges.
- **Duplicate / re-run any job.** The submit form pre-fills from the original job's parameters so you can tweak and resubmit.
- **Per-use-case LLM routing.** Every LLM call site has a registered use case that can be independently routed to OpenAI / Anthropic / Google / a local OpenAI-compatible server.
- **Fail-soft.** An LLM outage disables only the dependent features; everything else keeps working.
- **One-click restart.** `scripts/restart_services.ps1` and `POST /api/v1/admin/restart` relaunch all four runtimes on Windows.

Planned: multi-source ingest (podcasts, articles, forums, PDFs), a curated "source ranking" layer, an Author Studio for generating books/sites/decks/reels from the library, and the personal-brain direction. See [docs/feature-roadmap.md](docs/feature-roadmap.md).

---

## Prerequisites

- **Python 3.12+**
- **Node.js 20+** and npm
- **Redis** 7+ (native on Windows, or via Docker / Homebrew / apt)
- **YouTube Data API v3 key** — [Get one](https://console.cloud.google.com/apis/api/youtube.googleapis.com)
- **At least one LLM provider key.** Out of the box, routing defaults to OpenAI, so `OPENAI_API_KEY` is required unless you override every use case. Anthropic, Google, and local OpenAI-compatible endpoints are also supported.

---

## Quick start

> **Four processes run in parallel:** Redis, backend API, Celery worker, frontend dev server. Jobs will never progress past `pending` if the Celery worker is not running.

### 1. Install Redis

```bash
# Windows
winget install Redis.Redis                  # installs + starts as a Windows service on :6379

# macOS
brew install redis && brew services start redis

# Linux (Debian/Ubuntu)
sudo apt install redis-server && sudo systemctl start redis

# Any platform, via Docker
docker compose up -d redis
```

Verify with `redis-cli ping` → `PONG`.

### 2. Backend

```bash
cd backend
python -m venv venv
./venv/Scripts/pip install -r requirements.txt          # Windows
./venv/Scripts/pip install -r requirements-dev.txt      # Windows
# (Linux/macOS: replace ./venv/Scripts/ with ./venv/bin/)
cp ../.env.example .env                                  # fill in YOUTUBE_API_KEY + OPENAI_API_KEY + JWT_SECRET
./venv/Scripts/alembic upgrade head
```

### 3. Frontend

```bash
cd frontend
npm install
```

### 4. Start everything (three terminals)

```bash
# Terminal 1 — API
cd backend && ./venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — Celery worker (--pool=solo mandatory on Windows)
cd backend && ./venv/Scripts/celery -A app.tasks.celery_app worker --loglevel=info --pool=solo

# Terminal 3 — Frontend
cd frontend && npm run dev
```

### 5. Open the app

- Frontend: **http://localhost:5173**
- Backend health: **http://localhost:8000/api/v1/health**

For the full dev loop — migrations, tests, lint, commit conventions — see [docs/contributing.md](docs/contributing.md).

---

## Restarting services (Windows)

All four runtimes can be killed and relaunched in one shot via `scripts/restart_services.ps1`:

```powershell
./scripts/restart_services.ps1                       # full restart
./scripts/restart_services.ps1 -SkipFrontend         # leave Vite alone
./scripts/restart_services.ps1 -KillOnly             # kill without relaunching
```

Or from inside the running backend:

```bash
curl -X POST "http://localhost:8000/api/v1/admin/restart" \
     -H "Authorization: Bearer $TOKEN"
```

The endpoint spawns the restart script as a detached child, returns `202`, then kills its own uvicorn after a short delay. The new backend comes up on the same port within ~5–10 s.

---

## How it works (one paragraph each)

1. **Submit a job.** Topic (AI-discovered videos), channel (paste URLs), or subscription (fire-and-forget ingestion of a channel's uploads playlist).
2. **Approve.** Topic and channel jobs pause for you to review the discovered video list; subscription jobs skip this step.
3. **Ingest.** Transcripts are fetched from YouTube (with a Whisper fallback), chunked at 512 tokens with timestamp mapping, and embedded once per video using a multilingual model (`paraphrase-multilingual-MiniLM-L12-v2`). Already-indexed videos are reused for free.
4. **Report.** Topic and channel jobs run a LangGraph map-reduce agent that produces an HTML report grounded in the transcripts. Subscription jobs skip this step.
5. **Ask.** Per-job, library-wide, or across-all-past-Q&A-history — every answer is citation-grounded with clickable timestamps.
6. **Harvest.** Any video can be turned into a structured knowledge artifact. All Q&As and all knowledge artifacts stream out as JSONL for fine-tuning.

For the deeper walk-through, see [docs/architecture.md](docs/architecture.md).

---

## Running with a local LLM

Every LLM call site is a named use case that can be individually routed. Point any use case at a local OpenAI-compatible server (LM Studio, Ollama, vLLM, llama.cpp-server) by choosing the `local` provider.

```env
LLM_LOCAL_BASE_URL=http://localhost:1234/v1
LLM_LOCAL_API_KEY=not-needed

# Route cheap chatty use cases local; keep high-stakes ones on a frontier model.
LLM_USE_CASE_CONFIG=qa_clarification=local:qwen/qwen3-8b-instruct,qa_sub_query_expansion=local:qwen/qwen3-8b-instruct,report_map_chunks=local:qwen/qwen3-8b-instruct,qa_formulate_answer=openai:gpt-5:medium,knowledge_synthesize_report=anthropic:claude-opus-4-5:medium
```

Format: `use_case=provider:model[:reasoning]`, comma-separated. Providers: `openai`, `anthropic`, `google`, `local`. Reasoning (optional): `off` / `minimal` / `low` / `medium` / `high` / `auto`. Any use case not listed falls back to the registry default in `backend/app/services/llm_routing.py::USE_CASE_REGISTRY`. Full reference in [CLAUDE.md](CLAUDE.md#llm-configuration).

**Benchmark your config.** `backend/scripts/stress_test_llm.py` sweeps concurrency levels and reports latency percentiles + aggregate throughput:

```bash
./venv/Scripts/python backend/scripts/stress_test_llm.py --use-case qa_formulate_answer
./venv/Scripts/python backend/scripts/stress_test_llm.py --provider local --model qwen/qwen3-9b --concurrency 1 2 4 8
```

Embeddings are already local (CPU SentenceTransformer). No embeddings-API cost.

---

## Fail-soft behavior

At boot the app probes every unique `(provider, model)` pair once. If any probe fails the app still starts:

- A banner at the top of every page lists affected features and offers a **Retry** button.
- LLM-dependent primary actions disable themselves (Ask question, Generate report, Extract knowledge) with an inline explainer pointing at the offending use case.
- Non-LLM features stay fully interactive: browsing jobs, viewing past reports, browsing the library, downloading exports, managing subscriptions.

A dead local model, an expired API key, or a rate-limited account never bricks the app.

---

## Fine-tuning your own model

Four streaming JSONL endpoints turn your accumulated library into training-ready datasets:

- `GET /api/v1/exports/qa-dataset/openai.jsonl` — Q&A, OpenAI chat format
- `GET /api/v1/exports/qa-dataset/tuple.jsonl` — Q&A, plain `{system, user, assistant}` tuples
- `GET /api/v1/exports/knowledge-dataset/openai.jsonl` — knowledge artifacts, chat format
- `GET /api/v1/exports/knowledge-dataset/tuple.jsonl` — knowledge artifacts, tuple format

Feed them to OpenAI fine-tuning or Vertex tuning jobs externally today. An in-app fine-tune runner is planned — see [docs/finetune_design.md](docs/finetune_design.md).

---

## Project layout

```
Pratidhvani/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── config.py            # Settings (reads .env)
│   │   ├── routers/             # HTTP endpoints (auth, jobs, qa, library, channels,
│   │   │                        #   qa_history, knowledge, exports, admin, health, ws)
│   │   ├── models/              # SQLAlchemy ORM
│   │   ├── schemas/             # Pydantic request/response models
│   │   ├── services/            # Business logic (youtube, chroma, llm_routing, ...)
│   │   ├── agents/              # LangGraph agents (search, report, qa, knowledge, qa_history)
│   │   ├── tasks/               # Celery task definitions
│   │   ├── websocket/           # WebSocket connection manager
│   │   └── utils/               # Chunking, HTML builder, YouTube helpers
│   ├── tests/                   # 168 pytest tests
│   ├── alembic/                 # Migrations
│   ├── scripts/                 # stress_test_llm, etc.
│   └── requirements*.txt
├── frontend/
│   ├── src/
│   │   ├── pages/               # Login, Submit, JobsList, JobDetail, Library, LibraryQA,
│   │   │                        #   QAHistoryChat, Exports, ...
│   │   ├── hooks/               # React Query hooks + WebSocket bridge
│   │   ├── services/            # API client + WebSocket client
│   │   ├── stores/              # Zustand UI state
│   │   ├── components/          # StatusBadge, ProgressBar, LoadingSpinner, ...
│   │   └── types/               # TypeScript interfaces
│   └── package.json
├── docs/                        # See the Documentation table above
├── scripts/                     # restart_services.ps1
├── .env.example
├── docker-compose.yml
├── CHANGELOG.md
├── CLAUDE.md                    # Claude Code project guidance
└── README.md                    # this file
```

---

## Environment variables

See [.env.example](.env.example) for the template and [CLAUDE.md](CLAUDE.md#environment-variables) for the full table.

Most important knobs:

| Variable | Required | Purpose |
|----------|----------|---------|
| `YOUTUBE_API_KEY` | yes | YouTube Data API v3 |
| `OPENAI_API_KEY` | conditional | required if any use case routes to `openai` (defaults do) |
| `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` | conditional | required if the corresponding provider is configured |
| `JWT_SECRET` | yes | any long random string — don't reuse across environments |
| `LLM_USE_CASE_CONFIG` | no | per-use-case provider/model/reasoning override |
| `LLM_LOCAL_BASE_URL` | no | endpoint for `local` provider (LM Studio / Ollama / vLLM / llama.cpp-server) |

---

## What's new

See [CHANGELOG.md](CHANGELOG.md).

---

## Contributing

Setup, conventions, commit style, and PR checklist live in [docs/contributing.md](docs/contributing.md). Testing strategy in [docs/testing.md](docs/testing.md). Please read both before opening your first PR.

---

## License

TBD — the project is open-source in spirit today; the license will be finalized before the first tagged release. See [docs/saas-roadmap.md §License](docs/saas-roadmap.md) for the considered options.
