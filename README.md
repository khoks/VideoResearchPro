# VideoResearchPro

A full-stack web application for YouTube video research. Submit jobs to fetch transcripts from YouTube videos (by topic search or channel), build vector DB RAGs, generate HTML reports via LangGraph agents, and ask citation-backed questions against the collected data.

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

## How It Works

1. **Submit a job** — Choose topic-based (AI searches YouTube for you) or channel-based (provide channel URLs directly). Configure number of videos, duration filters, and search instructions.

2. **Review & approve videos** — The system finds matching videos and pauses for your approval. The video list auto-populates in real time via WebSocket — no page refresh needed. Deselect any you don't want, then approve to continue.

3. **Automatic processing** — Transcripts are fetched (with automatic language fallback — tries English first, then any available language like Hindi or Spanish), chunked at 512 tokens with timestamp mapping, and embedded into a per-job vector database (ChromaDB). A LangGraph report agent generates a comprehensive HTML research report using map-reduce.

4. **View report & ask questions** — Read the generated report in a full-page modal viewer. Ask follow-up questions in the Q&A panel — a 4-step pipeline retrieves relevant RAG chunks + report text, refines the context through an LLM compactor (reducing ~45K chars to ~2-4K focused extracts), generates an answer, and extracts citation references with clickable YouTube timestamp links.

## Project Structure

```
VideoResearchPro/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── config.py            # Settings (reads .env)
│   │   ├── routers/             # API endpoints (jobs, qa, ws, health)
│   │   ├── models/              # SQLAlchemy ORM (job, video, qa_exchange)
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
│   │   ├── pages/               # SubmitJobPage, JobsListPage, JobDetailPage
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
| WS | `/ws/jobs` | Real-time progress (subscribe/unsubscribe per job) |
