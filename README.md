# VideoResearchPro

A full-stack web application for YouTube video research. Run **topic**, **channel**, or **channel-subscription** jobs that feed a **shared global video library**, generate HTML reports via LangGraph agents, and ask citation-backed questions either scoped to a single job or across the **entire library**. Transcripts and embeddings are computed once per video and reused across every job that references them.

## Features

- **Topic research** — Describe a topic; AI finds, ranks, and summarizes the best videos.
- **Preferred channels filter (topic jobs)** — Optionally paste creator handles or channel URLs; the Search Agent walks each channel's uploads directly and keyword-filters them against your topic, alongside the broad YouTube searches. Creator names never end up stuffed into raw query strings.
- **Channel research** — Paste channel URLs; pull the latest N videos per channel.
- **Channel subscriptions** — Subscribe to a channel; every current and future video is ingested and indexed automatically.
- **Global video library** — One canonical copy of every transcribed video, reused across all jobs.
- **Library-wide Q&A** — Ask questions against the entire library of videos, not just one job.
- **Multilingual** — Transcribes whatever the speaker says (Hindi, Urdu, English, mixed); answers in your chosen language.
- **Citation-grounded Q&A** — Every answer includes clickable YouTube timestamps back to the source.
- **Duplicate / re-run any job** — The Jobs list and Job Detail pages both expose a **Duplicate / Re-run** action that opens the submit form pre-filled with the original job's parameters (topic, instructions, duration filters, preferred channels, channel list, etc.). Tweak what you want and resubmit — a brand-new job with a new ID is created, the original is untouched.
- **Job Parameters card** — The detail page shows every submission parameter in a read-only card so you can see exactly what was asked for, months later.
- **One-click restart** — `scripts/restart_services.ps1` and a protected `POST /api/v1/admin/restart` endpoint bring Redis, the backend, the Celery worker, and the frontend back up in a single shot. Detached processes now write to `.uvicorn.log`, `.celery.log`, and `.frontend.log` at the repo root so post-mortem debugging stays possible.

## Prerequisites

- **Python 3.12+**
- **Node.js 18+** and npm
- **Redis** (installed natively on Windows, or via Docker on Linux/macOS)
- **YouTube Data API v3 key** — [Get one here](https://console.cloud.google.com/apis/api/youtube.googleapis.com)
- **OpenAI API key** — [Get one here](https://platform.openai.com/api-keys)

## Quick Start

> **The app requires 4 processes running simultaneously:**
> 1. **Redis** — as a service or Docker container
> 2. **Backend API** — `uvicorn` in `backend/`
> 3. **Celery worker** — required for all job processing; `--pool=solo` is mandatory on Windows
> 4. **Frontend** — `npm run dev` in `frontend/`
>
> Jobs will never progress past "pending" if the Celery worker is not running.

### 1. Install Redis

**Windows:**
```bash
winget install Redis.Redis
```
This installs Redis and starts it as a Windows service on port 6379 automatically.

**macOS:**
```bash
brew install redis
brew services start redis
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install redis-server
sudo systemctl start redis
```

**Docker (any platform):**
```bash
docker compose up -d redis
```

Verify Redis is running:
```bash
redis-cli ping
# Should return: PONG
```

### 2. Set up the Backend

```bash
cd backend
python -m venv venv

# Install dependencies
./venv/Scripts/pip install -r requirements.txt        # Windows
# ./venv/bin/pip install -r requirements.txt          # Linux/macOS

# Install dev dependencies (for testing)
./venv/Scripts/pip install -r requirements-dev.txt    # Windows
# ./venv/bin/pip install -r requirements-dev.txt      # Linux/macOS

# Configure environment
cp ../.env.example .env
```

Edit `backend/.env` and fill in your API keys:
```
YOUTUBE_API_KEY=your-youtube-api-key
OPENAI_API_KEY=your-openai-api-key
```

### 3. Set up the Frontend

```bash
cd frontend
npm install
```

### 4. Start All Services

You need **three terminals** (Redis runs as a service/container; open one terminal for each of the following):

**Terminal 1 — Backend API server:**
```bash
cd backend
./venv/Scripts/python -m uvicorn app.main:app --reload --port 8000    # Windows
# ./venv/bin/python -m uvicorn app.main:app --reload --port 8000      # Linux/macOS
```

**Terminal 2 — Celery worker:**
```bash
cd backend
./venv/Scripts/celery -A app.tasks.celery_app worker --loglevel=info --pool=solo    # Windows
# ./venv/bin/celery -A app.tasks.celery_app worker --loglevel=info                  # Linux/macOS
```

> Note: `--pool=solo` is required on Windows. Linux/macOS can omit it to use the default prefork pool.

**Terminal 3 — Frontend dev server:**
```bash
cd frontend
npm run dev
```

### 5. Open the App

Navigate to **http://localhost:5173** in your browser.

The backend API is available at **http://localhost:8000** (health check: `GET /api/v1/health`).

## Restarting Services

All four runtimes (Redis, backend, Celery worker, frontend dev server) can be killed and relaunched in one shot via `scripts/restart_services.ps1` on Windows.

**From the command line:**
```powershell
# Full restart of everything:
./scripts/restart_services.ps1

# Backend + Celery only; leave the frontend dev server alone:
./scripts/restart_services.ps1 -SkipFrontend

# Kill the four runtimes without restarting (handy when debugging):
./scripts/restart_services.ps1 -KillOnly
```

The script kills processes by port (`:8000` backend, `:5173` frontend) and by command-line match (`celery`), verifies the Redis Windows service is running (auto-starts it if not), and relaunches every service detached with `-WindowStyle Hidden`. Every step is mirrored to `restart_services.log` at the repo root so you can see what happened even when the scripts run without a console.

**From the running backend** (the endpoint is authenticated, so use your JWT):
```bash
curl -X POST "http://localhost:8000/api/v1/admin/restart" \
     -H "Authorization: Bearer $TOKEN"
```

The endpoint returns `202 Accepted` immediately, spawns `restart_services.ps1` as a detached child process, then sleeps for the configured delay (default 2 s) before killing its own uvicorn process. The new backend comes up on the same port within ~5–10 s. Useful query params: `?skip_frontend=true`, `?delay=5`. Self-restart is wired up for Windows hosts only.

## How It Works

1. **Pick a job type**
   - **Topic** — AI searches YouTube from a topic + instructions you provide.
   - **Channel** — You paste channel URLs; the latest N videos from each are pulled.
   - **Subscription** — You subscribe to a channel; every current and future video is ingested automatically. No approval step, no per-job report — pure library ingestion.

2. **Review & approve videos** (Topic and Channel jobs only) — The system finds matching videos and pauses for your approval. The list auto-populates in real time via WebSocket. Deselect any you don't want, then approve to continue. Subscription jobs skip this step entirely.

3. **Global video library** — Transcripts and embeddings are computed **once per video** and stored in a single global ChromaDB collection. If a later job references a video that's already in the library, it's reused instantly — no re-fetch, no re-transcribe, no re-embed. Deleting a job unlinks its videos but does not remove them from the library.

4. **Automatic processing** — Transcripts are fetched from YouTube (with a Whisper fallback when captions are unavailable), chunked at 512 tokens with timestamp mapping, and embedded using a multilingual model (`paraphrase-multilingual-MiniLM-L12-v2`) that handles Hindi, Urdu, English, Russian, and 50+ other languages. Topic and Channel jobs then generate an HTML research report via a LangGraph map-reduce agent.

5. **Per-job Q&A** — Ask questions inside a single job. Retrieval is filtered to the job's approved videos. Citations link back to the source video with `&t=` timestamps.

6. **Library-wide Q&A** (new) — Ask questions across your entire library of transcribed videos, not just one job. Useful for cross-channel research or revisiting subscribed content.

7. **Multilingual answers** — Whisper transcribes speakers in their native language(s), including code-mixed audio. The Q&A agent accepts an `answer_language` parameter and translates quoted non-English context into your chosen language while preserving proper nouns.

8. **Duplicate & iterate** — Every job is permanently browsable from the Jobs list. Click through to a detail page to see the full parameter set you submitted plus the live run state, approval queue, report, and Q&A history. Hit **Duplicate / Re-run** from either the list row or the detail header to spin up a new job seeded from the old one. No backend migration — the form just round-trips the stored `Job` row back into its inputs.

## Project Structure

```
VideoResearchPro/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── config.py            # Settings (reads .env)
│   │   ├── routers/             # API endpoints (jobs, qa, channels, library, ws, health)
│   │   ├── models/              # SQLAlchemy ORM (job, video, channel, job_video, qa_exchange, library_qa_exchange)
│   │   ├── schemas/             # Pydantic request/response models
│   │   ├── services/            # Business logic (youtube, chroma, progress, llm)
│   │   ├── agents/              # LangGraph agents (search, report, qa)
│   │   ├── tasks/               # Celery task definitions
│   │   ├── websocket/           # WebSocket connection manager
│   │   └── utils/               # Chunking, HTML builder, YouTube helpers
│   ├── tests/                   # pytest test suite (36 tests)
│   ├── alembic/                 # Database migrations
│   ├── data/                    # Runtime data (SQLite DB, ChromaDB, reports)
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── src/
│   │   ├── pages/               # SubmitJobPage, JobsListPage, JobDetailPage, LibraryPage, LibraryQAPage
│   │   ├── hooks/               # React Query hooks + WebSocket bridge
│   │   ├── services/            # API client + WebSocket client
│   │   ├── stores/              # Zustand UI state
│   │   ├── components/          # StatusBadge, ProgressBar, LoadingSpinner
│   │   └── types/               # TypeScript interfaces
│   └── package.json
├── docs/                        # Architecture, requirements, UI design docs
├── .env.example                 # Environment variable template
├── docker-compose.yml           # Redis (alternative to native install)
└── CLAUDE.md                    # Claude Code project guidance
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `YOUTUBE_API_KEY` | Yes | — | YouTube Data API v3 key |
| `OPENAI_API_KEY` | Yes | — | OpenAI API key for GPT-4.1 |
| `DATABASE_URL` | No | `sqlite:///./data/videoresearchpro.db` | SQLAlchemy DB connection |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis for WebSocket pub/sub |
| `CELERY_BROKER_URL` | No | `redis://localhost:6379/1` | Celery task broker |
| `CELERY_RESULT_BACKEND` | No | `redis://localhost:6379/2` | Celery result storage |
| `LLM_MODEL` | No | `gpt-4.1` | OpenAI model name |
| `CHROMA_PERSIST_DIR` | No | `./data/chroma` | ChromaDB storage path |
| `REPORTS_DIR` | No | `./data/reports` | Generated HTML reports path |

## Running Tests

```bash
cd backend

# All tests
./venv/Scripts/python -m pytest tests/ -v

# Single test file
./venv/Scripts/python -m pytest tests/test_routers/test_jobs.py -v

# Single test
./venv/Scripts/python -m pytest tests/test_routers/test_jobs.py::test_create_topic_job -v
```

Tests use an in-memory SQLite database and mock Celery tasks — no Redis required.

## API Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check |
| POST | `/api/v1/jobs` | Create a new research job |
| GET | `/api/v1/jobs` | List all jobs |
| GET | `/api/v1/jobs/{id}` | Get job details |
| PUT | `/api/v1/jobs/{id}/approve` | Approve video list and resume |
| POST | `/api/v1/jobs/{id}/cancel` | Cancel a running job |
| DELETE | `/api/v1/jobs/{id}` | Delete job and all associated data |
| GET | `/api/v1/jobs/{id}/videos` | List videos for a job |
| GET | `/api/v1/jobs/{id}/report` | View HTML report |
| POST | `/api/v1/jobs/{id}/qa` | Ask a question |
| GET | `/api/v1/jobs/{id}/qa` | Get Q&A history |
| POST | `/api/v1/library/qa` | Library-wide Q&A ask |
| GET | `/api/v1/library/qa` | Library-wide Q&A history |
| POST | `/api/v1/library/qa/clarify` | Library-wide clarify step |
| DELETE | `/api/v1/library/qa/{id}` | Delete a library Q&A exchange (optional) |
| GET | `/api/v1/library/videos` | Browse global video library |
| GET | `/api/v1/channels` | List all channels |
| GET | `/api/v1/channels/{id}` | Single channel detail |
| POST | `/api/v1/channels/{id}/subscribe` | Subscribe to a channel |
| POST | `/api/v1/channels/{id}/unsubscribe` | Unsubscribe from a channel |
| POST | `/api/v1/channels/{id}/sync` | Trigger a fresh sync |
| GET | `/api/v1/channels/{id}/videos` | List videos for a channel |
| POST | `/api/v1/admin/restart` | Restart Redis/backend/Celery/frontend (Windows only) |
| WS | `/ws/jobs` | Real-time progress (subscribe/unsubscribe per job) |

## What's New

- **Duplicate / re-run any job.** The Jobs list and each Job Detail page now have a **Duplicate / Re-run** button that navigates to the submit form with every parameter pre-filled from the original job. A new Job Parameters card on the detail page also surfaces the full submission payload in read-only form. Zero-backend-change feature — the frontend just round-trips the existing `Job` response back into the form.
- **Orphan backstop + worker log capture.** Every orchestrator task now runs a `finally`-clause safety net that fails any job still stuck in a transient status (`pending` / `searching` / `extracting` / `building_rag` / `generating_report`) when the task returns, so a silent bug can't strand the UI at 5% forever. `restart_services.ps1` now redirects each detached runtime's stdout + stderr to `.uvicorn.log`, `.celery.log`, `.celery.err.log`, and `.frontend.log` at the repo root so post-mortem debugging is possible.
- **Preferred channels on topic jobs.** The Search Agent now takes a `preferred_channels` list alongside the topic and instructions. The LLM produces a structured plan (`broad_queries` + `channel_keywords`); preferred channels are resolved to IDs and their uploads playlists are walked directly, then keyword-filtered. No more creator names getting stuffed into query strings.
- **Self-restart endpoint + PowerShell script.** `scripts/restart_services.ps1` kills and relaunches all four runtimes in one shot; `POST /api/v1/admin/restart` drives the same script from inside the running backend via a detached trampoline process.
- Videos are now globally deduplicated across jobs.
- New channel-subscription job type (fire-and-forget ingestion, no approval, no report).
- New library-wide Q&A endpoint and UI page.
- Multilingual transcription (Whisper fallback) and embeddings (`paraphrase-multilingual-MiniLM-L12-v2`).
- Single global ChromaDB collection (`videoresearchpro_global`) with per-job `video_id` metadata filtering.
