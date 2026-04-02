# VideoResearchPro — Requirements Specification

## Functional Requirements

### FR-1: Job Submission

- **FR-1.1**: Users can create **topic-based** jobs by providing:
  - Topic (required)
  - Natural language search instructions (optional) — guides the Search Agent's curation
  - Number of videos to find (default: 10, max: 100)
  - Duration range filter (min/max minutes, optional)
  - Channel type filters (optional, e.g. `["educational", "news"]`)

- **FR-1.2**: Users can create **channel-based** jobs by providing:
  - List of YouTube channel URLs or names (required, 1+)
  - Videos per channel (default: 10)
  - Duration range filter (min/max minutes, optional)

- **FR-1.3**: System enforces a maximum of 5 concurrent active jobs.

### FR-2: Video Discovery

- **FR-2.1**: Topic jobs use a LangGraph Search Agent that:
  - Interprets the user's topic and instructions
  - Generates multiple YouTube search queries
  - Executes searches via YouTube Data API v3
  - Deduplicates, filters by duration/channel type, and ranks results
  - Returns a curated list of video candidates

- **FR-2.2**: Channel jobs:
  - Resolve channel URLs/handles to channel IDs
  - Fetch recent videos from channel upload playlists
  - Filter by duration constraints

### FR-3: Video Approval

- **FR-3.1**: After discovery, the job pauses at `awaiting_approval` status.
- **FR-3.2**: Users see a checklist of discovered videos (all selected by default).
- **FR-3.3**: Users can deselect unwanted videos and approve to continue.
- **FR-3.4**: Only approved videos proceed to transcript extraction.

### FR-4: Transcript Extraction

- **FR-4.1**: System fetches transcripts using `youtube-transcript-api` for each approved video.
- **FR-4.2**: Preferred language: English (`en`), configurable. Falls back to any available transcript language (e.g., Hindi) if English is unavailable.
- **FR-4.3**: Failed transcripts are marked as `"unavailable"` without blocking other videos.
- **FR-4.4**: Rate limiting applied (configurable, default: 0.5s between requests).

### FR-5: RAG Construction

- **FR-5.1**: Transcripts are chunked at 512 tokens with 50-token overlap.
- **FR-5.2**: Each chunk preserves timestamp mapping (start/end seconds) from YouTube transcript segments.
- **FR-5.3**: Chunks are embedded with `all-MiniLM-L6-v2` and stored in a per-job ChromaDB collection.
- **FR-5.4**: Chunk metadata includes: video_id, video_title, channel_name, video_url, timestamps, word_count.

### FR-6: Report Generation

- **FR-6.1**: A LangGraph Report Agent generates an HTML report using map-reduce:
  - **Map phase**: Processes transcript chunks in batches (fitting 60% of LLM context)
  - **Reduce phase**: Hierarchically merges batch summaries
  - **Compose phase**: Generates final structured report

- **FR-6.2**: Topic job reports include:
  - Key facts and findings
  - Notable comments and perspectives
  - Conclusions and analysis
  - References with YouTube timestamp links
  - Speaker attribution where identifiable
  - Statistics (video count, total duration, word count, channels)

- **FR-6.3**: Channel job reports include statistics only (no LLM-generated analysis).

- **FR-6.4**: Reports are saved as standalone HTML files and served via API endpoint.

- **FR-6.5**: Report viewer displays in a full-page modal overlay (90vw x 90vh) with iframe.

### FR-7: Question & Answer

- **FR-7.1**: For completed jobs, users can ask questions in a chat-like interface.
- **FR-7.2**: Input is disabled and a loading spinner is shown while the Q&A agent processes.
- **FR-7.3**: A LangGraph Q&A Agent with 4-step pipeline:
  - Retrieves relevant chunks from ChromaDB (top-k = 15) + extracts clean text from HTML report
  - **Refines context**: An LLM compactor extracts only relevant passages (~2-4K chars) from the raw RAG+report context (~45K chars), preventing the answer LLM from being overwhelmed by irrelevant noise
  - Formulates an answer using the refined, focused context
  - Extracts citation references

- **FR-7.4**: Each answer includes references with:
  - Video title
  - Channel name
  - Clickable YouTube link with `&t=` timestamp parameter
  - Human-readable timestamp display

- **FR-7.5**: Q&A history is persisted per job.

### FR-8: Real-Time Progress

- **FR-8.1**: All active jobs push real-time progress updates via WebSocket.
- **FR-8.2**: Three message types: `job_progress` (percentage + message), `job_status_change`, `job_error`.
- **FR-8.3**: Frontend updates job data in-place without polling.
- **FR-8.4**: WebSocket reconnects automatically with exponential backoff + ping/pong keepalive.

### FR-9: Job Management

- **FR-9.1**: Users can view all jobs in a list with status, progress, and timestamps.
- **FR-9.2**: Users can cancel any running job (revokes Celery task).
- **FR-9.3**: Users can delete completed/cancelled/failed jobs from both the jobs list and job detail page (removes DB records, ChromaDB collection, report file).
- **FR-9.4**: Jobs list shows real-time progress for all active jobs simultaneously.
- **FR-9.5**: Video approval list auto-populates when job transitions to `awaiting_approval` (no manual refresh needed).

---

## Non-Functional Requirements

### NFR-1: Performance
- YouTube API calls rate-limited via token bucket (default 0.5s spacing)
- ChromaDB batch inserts (100 docs per batch)
- Map-reduce report generation handles 50+ videos / 250K+ words
- WebSocket fan-out via Redis pub/sub (not in-process)

### NFR-2: Reliability
- Each Celery task phase checks for cancellation before proceeding
- Failed transcripts don't block other videos
- Celery worker crash doesn't lose job state (status persisted in DB)
- WebSocket auto-reconnects with exponential backoff (1s → 30s max)

### NFR-3: Data Isolation
- One ChromaDB collection per job — no cross-job contamination
- Job deletion cascades to videos, Q&A exchanges, ChromaDB collection, and report file

### NFR-4: Configuration
All key parameters configurable via environment variables:
- LLM model, chunk size, overlap, top-k results
- Max concurrent jobs, max videos per job
- Rate limiting, API keys, database/Redis URLs

### NFR-5: Testability
- Backend tests use in-memory SQLite and mocked Celery tasks
- ChromaDB tests use EphemeralClient (no disk state)
- Frontend build includes TypeScript type checking

---

## External Dependencies

| Dependency | Purpose | Auth Required |
|------------|---------|---------------|
| YouTube Data API v3 | Video search, channel lookup, video details | API key |
| youtube-transcript-api | Transcript fetching (no auth) | No |
| OpenAI API | GPT-4.1 for all LangGraph agents | API key |
| Redis | Celery broker + result backend + pub/sub | Local instance |
| ChromaDB | Vector storage + similarity search | Local (embedded) |
