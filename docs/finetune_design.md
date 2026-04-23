# Fine-tune Execution — Design Doc

Status: design-only. No code in this pass. The implementer of this doc should be able to open it in isolation and build the feature without re-discovering prior decisions.

## 1. Overview

This feature adds the ability to kick off managed fine-tuning runs against the JSONL datasets that the Exports feature already produces (Q&A dataset and Knowledge dataset, each available in OpenAI chat format and plain tuple format). The UI lets the user pick a provider (OpenAI or Gemini/Vertex), a dataset, a base model, and optional hyperparameters, then submit a run. The backend uploads the dataset to the provider, starts the provider-native fine-tune job, tracks its lifecycle, and surfaces status + final metrics back in the UI. This closes the loop on the personal-wiki story: the user's accumulated Q&A and video-knowledge artifacts become parametric knowledge in a tuned model that can be used in (or outside) the app.

## 2. Database schema

One new table, `finetune_runs`. No joins back to datasets — the dataset is a snapshot-at-upload-time, and the export endpoints already reproduce it deterministically from the DB.

Columns:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID string (primary key) | Generated app-side with `uuid.uuid4().hex` for consistency with existing models. |
| `provider` | `Literal["openai", "gemini"]` | Stored as `VARCHAR`; enforced in Pydantic. |
| `dataset_type` | `Literal["qa", "knowledge", "both"]` | `"both"` uploads Q&A + Knowledge rows concatenated as a single file. |
| `model_name` | `str` | Base model to tune, e.g. `"gpt-4.1-mini-2025-04-14"` or `"gemini-1.5-flash-002"`. Validated against a provider-specific allow-list at submission time. |
| `status` | `Literal["pending", "uploading", "running", "succeeded", "failed", "cancelled"]` | Drives UI status badge + polling. |
| `provider_job_id` | `str \| None` | Provider-side job identifier (OpenAI `ftjob-...` or Vertex `tuningJobs/...`). `NULL` until the job is accepted. |
| `started_at` | `datetime \| None` | Set when provider returns a job ID. |
| `completed_at` | `datetime \| None` | Set on terminal state. |
| `error` | `str \| None` | Provider error message on `failed`. |
| `metrics_json` | `str \| None` | Raw provider-reported metrics (training loss, validation loss, step count, tuned model handle). JSON-encoded so we do not need to version a sub-schema as providers change theirs. |

Alembic-style CREATE TABLE sketch:

```sql
CREATE TABLE finetune_runs (
    id VARCHAR(36) PRIMARY KEY,
    provider VARCHAR(16) NOT NULL,
    dataset_type VARCHAR(16) NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    provider_job_id VARCHAR(128),
    started_at DATETIME,
    completed_at DATETIME,
    error TEXT,
    metrics_json TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_finetune_runs_status ON finetune_runs (status);
CREATE INDEX ix_finetune_runs_provider ON finetune_runs (provider);
```

Alembic revision (`*_finetune_runs.py`) would be straightforward — one `op.create_table` call plus the two `op.create_index` calls. No data backfill needed.

## 3. Service sketch

New file: `backend/app/services/finetune_service.py`. Uses the same provider-adapter pattern the codebase already favors (see `chroma_service.py` singleton style). The adapter interface is intentionally tiny so adding a third provider later (Anthropic, Together, etc.) is an afternoon.

```python
# backend/app/services/finetune_service.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class ProviderJobStatus:
    status: Literal["pending", "uploading", "running", "succeeded", "failed", "cancelled"]
    provider_job_id: str | None
    error: str | None
    metrics: dict[str, Any] | None   # serialized to metrics_json by caller


class FineTuneAdapter(ABC):
    @abstractmethod
    def upload_dataset(self, path: str) -> str:
        """Upload the JSONL file. Returns a provider-native file handle."""

    @abstractmethod
    def start_job(self, file_id: str, model_name: str, hyperparams: dict[str, Any]) -> str:
        """Start the tuning job. Returns the provider job id."""

    @abstractmethod
    def poll_status(self, job_id: str) -> ProviderJobStatus: ...

    @abstractmethod
    def cancel(self, job_id: str) -> None: ...


class OpenAIFineTuneAdapter(FineTuneAdapter):
    """
    Flow:
      1. client.files.create(file=open(path, "rb"), purpose="fine-tune")
           -> file_id
      2. client.fine_tuning.jobs.create(
             training_file=file_id,
             model=model_name,
             hyperparameters=hyperparams,   # {"n_epochs": "auto", ...}
         ) -> job.id
      3. client.fine_tuning.jobs.retrieve(job_id)
             -> job.status in {"validating_files","queued","running","succeeded","failed","cancelled"}
             -> normalize to our ProviderJobStatus enum
             -> metrics pulled from job.result_files via client.files.content(...)
                (training loss, validation loss) and stored raw in metrics_json.
      4. client.fine_tuning.jobs.cancel(job_id) for cancellation.
    """


class GeminiFineTuneAdapter(FineTuneAdapter):
    """
    Flow (Vertex AI):
      1. Upload JSONL to GCS:
           gs://{GCP_BUCKET}/videoresearchpro/finetune/{run_id}.jsonl
         using google-cloud-storage. Return the gs:// URI as the "file id".
      2. aiplatform.init(project=GCP_PROJECT_ID, location=GCP_REGION, credentials=...)
         job = aiplatform.TuningJob.create(
             source_model=model_name,        # e.g. "gemini-1.5-flash-002"
             training_data=gs_uri,
             hyper_parameters=hyperparams,   # {"epoch_count": 3, "learning_rate_multiplier": 1.0, ...}
         )
         return job.resource_name
      3. job = aiplatform.TuningJob(resource_name)
         state = job.state   # JOB_STATE_PENDING / RUNNING / SUCCEEDED / FAILED / CANCELLED
         metrics = job.tuning_data_stats + job.tuned_model  (tuned model handle lives here)
      4. job.cancel()
    """
```

Orchestration layer (same module):

```python
def run_finetune(run_id: str) -> None:
    """
    Celery task entrypoint. Called by the POST /runs route via .delay(run_id).
    Transitions:  pending -> uploading -> running -> (succeeded | failed).
    Persists provider_job_id, started_at, completed_at, error, metrics_json.
    Poll loop sleeps FINETUNE_POLL_INTERVAL_SECONDS between retrieve calls.
    On unexpected exception: status='failed', error=repr(exc), completed_at=now.
    """

def _materialize_dataset(dataset_type: Literal["qa", "knowledge", "both"]) -> str:
    """
    Reuse dataset_service.py generators to write a temp JSONL file
    (OpenAI chat format — the tuple format is export-only, not used for tuning).
    Returns the temp path. Caller is responsible for unlinking.
    """
```

Adapters are selected by a tiny factory:

```python
def get_adapter(provider: Literal["openai", "gemini"]) -> FineTuneAdapter:
    if provider == "openai":
        return OpenAIFineTuneAdapter()
    if provider == "gemini":
        return GeminiFineTuneAdapter()
    raise ValueError(f"unknown provider: {provider}")
```

Notes:

- The poll loop runs inside the Celery task — no new cron/scheduler needed. Celery's `acks_late=True` handles worker restarts cleanly.
- `metrics_json` stores the raw provider payload verbatim. The UI decides what to show; the DB does not own the schema.
- OpenAI's `fine_tuning.jobs.retrieve` is cheap — polling every 60s is fine. Vertex jobs are billed by the hour; the poll itself is a list-status call and also cheap.

## 4. UI sketch

New page: `frontend/src/pages/FineTunePage.tsx` at route `/finetune`. Auth-gated like every other page. Follows the existing inline-style + React Query + Zustand conventions.

Layout:

- **Header** — "Fine-tune runs" + a "Start new run" button that expands the form below.
- **Start new run form** (collapsed by default):
  - Provider dropdown — `openai` | `gemini`.
  - Dataset dropdown — `qa` | `knowledge` | `both`.
  - Model name text input with provider-specific placeholder. For OpenAI: placeholder `"gpt-4.1-mini-2025-04-14"`. For Gemini: placeholder `"gemini-1.5-flash-002"`.
  - Hyperparameters textarea — optional JSON blob. Empty = provider defaults. Validated client-side with `JSON.parse` before submit.
  - Submit button — disabled during inflight POST.
- **Runs table**:
  - Columns: `Provider`, `Dataset`, `Model`, `Status` (colored badge — reuse `StatusBadge` component), `Started`, `Duration`, `Metrics` (link that opens a drawer with `metrics_json` pretty-printed).
  - Rows sorted by `created_at` DESC.
  - Per-row "Cancel" button visible only when `status in {pending, uploading, running}`.
- **Polling**:
  - `useQuery(["finetune-runs"], listRuns, { refetchInterval: 30_000 })`.
  - When any row is in a non-terminal state, poll continues; the hook can drop the interval to `false` once all rows are terminal to save requests, but 30s-always is the simpler and acceptable default.
- **Navigation** — add a "Fine-tune" tab to `AppLayout`.

No charts. The `metrics_json` drawer is just a `<pre>` block until someone asks for more.

## 5. Routes (sketch, not implemented)

New router: `backend/app/routers/finetune.py`. All endpoints `dependencies=[Depends(get_current_user)]`.

```
POST   /api/v1/finetune/runs              # Start a run. Body: {provider, dataset_type, model_name, hyperparams?}
                                          #   -> creates DB row (status=pending)
                                          #   -> dispatches run_finetune.delay(run_id)
                                          #   -> returns the row
GET    /api/v1/finetune/runs              # List all runs, newest first
GET    /api/v1/finetune/runs/{id}         # Single run detail (polled by the UI)
POST   /api/v1/finetune/runs/{id}/cancel  # Revoke Celery task + call adapter.cancel()
                                          #   -> status=cancelled, completed_at=now
```

Schemas (`backend/app/schemas/finetune.py`):

- `FineTuneRunCreate` — request body for POST.
- `FineTuneRunResponse` — DB row serialized (Pydantic v2, `model_config = {"from_attributes": True}`).
- `FineTuneRunListResponse` — `{runs: list[FineTuneRunResponse]}`.

## 6. Required secrets / config

Add to `.env.example` and `backend/app/config.py`:

```env
# Fine-tune providers
OPENAI_API_KEY=sk-...                     # already present — reused for fine-tune
GCP_PROJECT_ID=my-gcp-project             # required for Gemini/Vertex
GCP_REGION=us-central1                    # default; override per-region
GCP_SERVICE_ACCOUNT_JSON=/path/to/sa.json # path to service account JSON, or the raw JSON inline
FINETUNE_POLL_INTERVAL_SECONDS=60         # how often the Celery task polls provider status
```

Loaded in `config.py`:

```python
class Settings(BaseSettings):
    # ... existing ...
    OPENAI_API_KEY: str
    GCP_PROJECT_ID: str | None = None
    GCP_REGION: str = "us-central1"
    GCP_SERVICE_ACCOUNT_JSON: str | None = None
    FINETUNE_POLL_INTERVAL_SECONDS: int = 60
```

`GeminiFineTuneAdapter` raises a clear startup error if `GCP_PROJECT_ID` is unset the first time someone tries to create a Gemini run — we deliberately do not fail app boot, since Gemini is optional.

New Python dependencies (add to `requirements.txt` when the feature is implemented):

- `google-cloud-aiplatform>=1.60` — Vertex AI TuningJob API.
- `google-cloud-storage>=2.14` — GCS upload for Gemini path.
- OpenAI SDK is already pinned for the rest of the app; no change there.

## 7. Open questions / future work

- **Billing visibility.** Fine-tune runs are expensive (OpenAI gpt-4.1-mini tuning is ~$3/1M training tokens; Vertex Gemini tuning is hourly). Before shipping, decide whether to show an upfront estimate (row count × tokens × provider rate), a post-hoc cost (from provider metrics), or both. Leaning toward estimate-on-submit as a confirmation modal.
- **Evaluation after tuning.** We have no held-out eval set today. Options: (a) hold out the last N% of exchanges on export, (b) let the user mark some Q&As as "eval set" in the UI, (c) leave it manual ("ask the tuned model a few questions and see"). Option (c) ships first, but (a) is probably right.
- **Deploying the tuned model back into the app.** Once a run succeeds, the provider returns a tuned-model handle (e.g. `ft:gpt-4.1-mini:...` or `projects/.../tunedModels/...`). Plumbing that into `get_llm()` as a new `purpose="tuned"` slot — or a per-job model override — is the natural next step. Needs a UI affordance on the run row ("Use this model for new Q&A") and a config row to persist the selection.
- **Dataset versioning / reproducibility.** Today the export endpoint reads live DB rows; a run started on Monday trains on different data than one started on Friday. Options: snapshot the JSONL file to disk and record its hash + row count on the `finetune_runs` row, or include a dataset `as_of` timestamp parameter at submit time. The hash-on-disk approach is cheap and gives us a real audit trail.
- **Multi-provider re-runs.** The UI currently treats each run as independent. A common ask will be "take the dataset from run #42 and kick it at Gemini too." Add a "Clone run" button once we see that request twice.
