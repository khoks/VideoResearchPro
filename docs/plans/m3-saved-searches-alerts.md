# M3 — Saved searches and alerts: plan

**Board:** [E-8.3](../initiatives.md#e-83--saved-searches-and-alerts-m3) · **Roadmap:** [M3](../feature-roadmap.md#m3--saved-searches--alerts-) · **Research date:** 2026-10-19 · **Status:** recommendation.

## Problem

A question the user cares about ("what do my sources say about rate cuts?") has to be re-asked by hand to learn whether the library's answer has moved. The roadmap wants a pinned question re-run on a schedule with a notification when the answer materially changes. Nothing in the app runs on a schedule today, so this plan also carries the project's first scheduler, which the newsletter (E-6.4) and Echo connector syncs (S-3.2.1) reuse.

## Verified current state (2026-10-18)

- `tasks/celery_app.py` configures the worker only; no `beat_schedule`, no beat process in `scripts/start.ps1`. Channel sync is manual (`POST /channels/{id}/sync`).
- Library Q&A: `run_library_qa_agent` in `agents/qa_agent.py`, called from `routers/library.py` with the tenant's visible set; references are extracted structurally (`extract_references`), so cited document ids are available without parsing prose.
- Quota: `quota_metering_service` meters `library_qa_exchanges` per month ([D-045](../decisions.md#d-045--quota-metering-enforce-before-record-after-success-2026-05-05)); the tier gate `saved_searches` exists in `TIER_CAPABILITIES` and the frontend mirror with nothing behind it.
- Email: `email_service.send_email` with SMTP or log fallback.
- Notifications: none; the WebSocket at `/ws/jobs` multiplexes per-job progress and could carry a `notifications` subscription.
- `document_visibility.created_at` records when a document became visible to a tenant, which is exactly the signal needed to know whether anything new has arrived since a saved search last ran.

## Chosen approach

### Scheduler (S-8.3.1)

One static Celery beat entry, `scheduler.tick`, every five minutes, run by **exactly one `celery beat` process** added to `start.ps1` and `restart_services.ps1` (Celery's docs require a single scheduler; the embedded `worker -B` form is "not recommended for production" and unverified with `--pool=solo` on Windows). The tick selects due rows from a `scheduled_runs` table (`kind`, `target_id`, `next_run_at`, `enabled`, `last_run_at`, `last_status`, `claimed_at`) with `UPDATE … WHERE next_run_at <= now AND claimed_at IS NULL` so a duplicate tick is harmless, advances `next_run_at`, and dispatches the kind's task through `task_routing_service.dispatch_for_user` so tier queues apply. `next_run_at` is computed with Celery's own `crontab(...).remaining_estimate()`; no cron strings are ever exposed. Human cadences (`daily`, `weekly`, `monthly`) with `hour`, `weekday` or `day_of_month` and an IANA `timezone`, as Exa Monitors and Perplexity do. `SCHEDULER_ENABLED` setting; `scripts/start.ps1` documents "run exactly one beat".

### Saved searches (S-8.3.2)

`saved_searches(id, tenant_id, question, answer_language, scope_json, cadence, hour, weekday, day_of_month, timezone, notify_email, enabled, last_run_at, last_answer_hash, last_reference_ids_json, last_answer_embedding_id)`; `scope_json` is `null` (library) or `{"shelf_id": …}` after M1. "Pin this question" on library Q&A answer cards; a `/saved-searches` page with last result, next run, pause and run-now. Gated on `require_feature("saved_searches")`, with a per-tier cap on active rows in `TIER_CAPABILITIES` (comparable products cap at 3, 5 and 15 per plan).

### Re-run and change detection (S-8.3.3)

Three stages, cheapest first:

1. **Gate.** If no `document_visibility` row for the tenant (or in the scope) is newer than `last_run_at`, skip the re-run and record `unchanged (no new sources)`. Cost then scales with ingest, not with the number of saved searches.
2. **Deterministic signals.** Run the library Q&A agent (quota enforced before, recorded after, per D-045). Compare the cited document set to `last_reference_ids_json` (Jaccard) and the new answer's embedding (same MiniLM embedder as `qa_library_global`) to the stored one (distance). Either crossing its threshold marks "changed". Thresholds live in settings, are **pre-registered before tuning**, and are calibrated on the app's own Q&A history, which already holds every past answer; no product publishes its algorithm and no published cosine threshold for "same answer" exists.
3. **Judge only on disagreement.** When the two signals disagree, one cheap-tier call (`saved_search_judge`, about $0.0002 per run on a nano model) returns `{changed, what_changed}` and writes the notification text.

A `saved_search_runs(id, saved_search_id, ran_at, status, answer, references_json, changed, diff_summary, exchange_id)` row per run; the exchange is also stored as a normal `library_qa_exchanges` row with `scope_json` carrying `saved_search_id`, so it joins the history and the Q&A library index.

### Notifications

`notifications(id, tenant_id, kind, title, body, href, read_at, created_at)` and `GET/PATCH /api/v1/notifications`; a bell in the sidebar chrome; a `subscribe:notifications` message on the existing WebSocket for live badge updates. Email through `email_service` when `notify_email` is on (SMTP is already fail-soft). Web push is **deferred**: `pywebpush` is MPL-2.0 and single-maintainer, it needs HTTPS, a service worker and VAPID keys, and iOS only delivers to Home-Screen web apps.

## Alternatives rejected

| Option | Why not |
|---|---|
| RedBeat (Apache-2.0) | Redis-backed dynamic beat entries with a lock; only needed for highly available beat. Rows in SQLite keep schedule state inside the backup. Upgrade path if ever needed. |
| `django-celery-beat` | Django ORM only. |
| `celery-sqlalchemy-scheduler` | Archived since 2022. |
| APScheduler | 3.x would be a second scheduler stack beside Celery inside the API process; 4.0 is still alpha ("do not use in production"). |
| `croniter` cron strings | Alive again (6.2.4, MIT, pallets-eco), but users should never see cron; Celery's `crontab` covers daily / weekly / monthly. `python-crontab` is LGPL-3.0 and the wrong tool. |
| Answer-hash change detection | LLM nondeterminism makes almost every run "changed". |
| LLM judge on every run | Pays a call per run; the gate and deterministic signals remove most of them. |
| Web push in v1 | Dependencies and platform constraints above. |

## Schema deltas

```
scheduled_runs(id, tenant_id, kind, target_id, next_run_at, cadence_json, last_run_at, last_status, claimed_at, enabled, created_at)
saved_searches(...)            as above
saved_search_runs(...)         as above
notifications(id, tenant_id, kind, title, body, href, read_at, created_at)
library_qa_exchanges.scope_json (shared with M1)
TIER_CAPABILITIES["saved_searches_active_cap"]
```

## API deltas

```
GET/POST           /api/v1/saved-searches
GET/PATCH/DELETE   /api/v1/saved-searches/{id}
POST               /api/v1/saved-searches/{id}/run-now
GET                /api/v1/saved-searches/{id}/runs
GET/PATCH          /api/v1/notifications            (list, mark read)
WS                 subscribe:notifications
```

Registry: `saved_search_judge` (economy tier, structured JSON). Settings: `SCHEDULER_ENABLED`, `SCHEDULER_TICK_SECONDS`, `SAVED_SEARCH_JACCARD_THRESHOLD`, `SAVED_SEARCH_EMBEDDING_THRESHOLD`.

## Modules touched

`tasks/celery_app.py` (beat schedule), `tasks/scheduler_tasks.py` and `tasks/saved_search_tasks.py` (new), `services/scheduler_service.py`, `services/saved_search_service.py`, `services/notification_service.py` (new), `models/{scheduled_run,saved_search,saved_search_run,notification}.py`, `routers/saved_searches.py` and `routers/notifications.py` (new), `websocket/manager.py` (notification channel), `services/tier_service.py` (cap), `services/llm_routing.py` (judge use case), `scripts/start.ps1` and `restart_services.ps1` (beat), `frontend/src/pages/SavedSearchesPage.tsx` (new), `LibraryQAPage.tsx` (pin), `layouts/AppLayout.tsx` (bell), `services/wsClient.ts`.

## Risks

- **Beat singleton** on self-host: two beats double the tick load; row claiming prevents double runs but not double load. Document and detect (the tick can record its process id in a one-row table and warn).
- **Windows**: Celery officially stopped supporting Windows at 4.x; the worker already runs with `--pool=solo`; beat as a separate process is the safe shape.
- **Threshold calibration** differs by language and corpus; keep the pre-registration discipline of [D-068](../decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18).
- **Cost control**: without the gate every saved search is an LLM call per cadence; with it, cost follows ingest. The tier cap bounds the worst case.
- **Clock and timezone**: `next_run_at` in UTC computed from the user's IANA zone; DST transitions are handled by `zoneinfo`, test them.

## Test strategy

- Scheduler: due selection, claim lease, duplicate tick harmless, disabled rows skipped, `next_run_at` across a DST change, dispatch routed per tier.
- Saved searches: isolation, cap enforced, quota enforced before run (D-045), run-now.
- Change detection: gate skips when nothing new is visible; unchanged citations and a near-identical answer do not notify; a changed cited set does; judge called only on disagreement (LLM factory patched); a failed run leaves the previous result intact.
- Notifications: created on change, email sent when enabled (SMTP patched), read state, WebSocket message shape.
- Frontend: type-check; pin → list → run-now smoke.

## First PR (S-8.3.1)

The scheduler alone: `scheduled_runs`, the beat entry, the tick task with claiming, per-kind dispatch, `SCHEDULER_ENABLED`, the launcher scripts, and tests with a fake kind. No saved searches yet. It is the dependency for M3, E-6.4 and S-3.2.1 and is independently reviewable.

## Open questions

1. Per-tier caps on active saved searches: suggested Pro 10, Studio 50, Free 0 (the gate already excludes Free). Agree?
   **Answered 2026-10-25** by [D-112](../decisions.md#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25): ratified as built in S-8.3.2, Free 0, Pro 10, Studio 50.
2. Should a saved search be able to target a *job* scope (re-ask on a finished job as new Q&A land) or only library and shelf scopes?
   **Answered 2026-10-25** by [D-112](../decisions.md#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25): library and shelf scopes only, ratified as built.

## Sources (fetched 2026-10-19)

Celery periodic-tasks, configuration (`beat_max_loop_interval`), `celery.schedules` and FAQ pages; RedBeat repository and PyPI; `celery-sqlalchemy-scheduler` repository state; APScheduler PyPI and migration guide; croniter PyPI and pallets-eco repository; `python-crontab` PyPI (LGPL); Google Alerts help; Perplexity Scheduled Tasks help centre; ChatGPT Tasks help (via search); Exa Websets Monitors API; `pywebpush` and `py-vapid` PyPI; MDN Push API; WebKit web-push post. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
