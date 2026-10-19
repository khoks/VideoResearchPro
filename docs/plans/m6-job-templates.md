# M6 — Job templates: plan

**Board:** [E-8.6](../initiatives.md#e-86--job-templates-m6) · **Roadmap:** [M6](../feature-roadmap.md#m6--job-templates--playbooks-) · **Research date:** 2026-10-19 · **Status:** recommendation.

## Problem

A good research run is a recipe: instructions, filters, preferred channels, source types, depth, visual flag. Today the only way to reuse one is "Duplicate", which copies a single job. The roadmap wants named, reusable templates; the onboarding wizard (M10) needs starter templates so a first job is one click.

## Verified current state (2026-10-18)

- `JobCreate` (`backend/app/schemas/job.py`): `job_type`, `topic`, `search_instructions`, `num_videos` (1–500), `min/max_duration_minutes`, `channel_type_filters`, `preferred_channels`, `source_types`, `output_length` (auto / brief / standard / deep), `visual_analysis`, `channel_list`, `videos_per_channel` (1–50). There is **no date-range field**.
- Duplicate flow: `JobsListPage` and `JobDetailPage` navigate to `/submit` with `state.cloneFrom`; `SubmitJobPage.jobToFormState(job)` rebuilds the form. Two defects: it resets `output_length` to `auto` and drops `visual_analysis`. The form state is also persisted in `localStorage` under `FORM_STATE_KEY`, an informal "last template".
- No `job_templates` table or route. Tier capabilities have no template entry (templates are a convenience, not a tiered feature).
- `users` has no onboarding columns (M10 adds them).

## Chosen approach

- **Fix the Duplicate flow first** (T-8.6.1.0): carry `output_length` and `visual_analysis` through `jobToFormState`. Templates build on that path.
- **Freeze versus variable** (Postman's rule: collection-level values are fixed, environment values vary). Frozen in the template: `job_type`, `search_instructions` (with an optional `{{topic}}` placeholder), `channel_type_filters`, duration bounds, `preferred_channels`, `channel_list`, `videos_per_channel`, `num_videos`, `source_types`, `output_length`, `visual_analysis`. Variable at run time: `topic` (topic jobs), the job's display name, and a **relative** publish window. Because `JobCreate` has no date field, add `published_after_days` (resolved at run time) rather than absolute dates so a template stays reusable; it threads into the search agent as a ranking preference, never a filter ([D-059](../decisions.md#d-059--selection-quotas-preferred-channel-guarantee--concentration-cap-2026-07-30) posture).
- **Versioned snapshots** (Grafana's model): `job_templates(id, tenant_id NULL for built-ins, builtin_key, name, description, job_type, version, parameters_json, is_latest, created_at)` with immutable rows per save and `jobs.template_id` + `jobs.template_version` for provenance, so "re-run with the template as it was" works and the version history is diffable. Keep the last twenty versions per template.
- **Validation** re-runs the `JobCreate` Pydantic model at instantiation so a stale template (a removed source type, a tier cap exceeded) cannot create an invalid job; errors surface in the picker.
- **Starter templates** (S-8.6.2): five built-ins inserted by migration and versioned by `builtin_key` (topic scan, channel deep-dive, podcast digest, mixed-source debate, subscription follow); read-only; used by M10's first-job step.
- **UI**: "Save as template" on `JobDetailPage`; a "From template" picker on `SubmitJobPage` that fills the form through the same `jobToFormState` path and leaves only the variable fields to edit; a small `/templates` list with rename and delete.

## Alternatives rejected

| Option | Why not |
|---|---|
| Keep using `localStorage` form state as "the template" | Per device, single slot, unnamed, invisible to onboarding. |
| Mutable templates without versions | A job that ran "with template X" would point at parameters that no longer exist. |
| Absolute date ranges in templates | Stale after a day; a relative window is what "weekly scan" means. |
| Tier-gating templates | No cost to the operator; gating would only annoy. |

## Schema deltas

```
job_templates(id, tenant_id NULL, builtin_key NULL, name, description, job_type, version INT, parameters_json, is_latest BOOL, created_at)
                UNIQUE(tenant_id, name, version); INDEX(tenant_id, is_latest)
jobs.template_id NULL, jobs.template_version NULL
JobCreate.published_after_days INT NULL   (and jobs.published_after_days)
```

## API deltas

```
GET/POST          /api/v1/job-templates
GET/PUT/DELETE    /api/v1/job-templates/{id}            (PUT creates a new version)
GET               /api/v1/job-templates/{id}/versions
POST              /api/v1/jobs/{id}/save-as-template
POST              /api/v1/jobs?template_id=&template_version=   (provenance recorded)
```

## Modules touched

`models/job_template.py`, one Alembic revision (table, two `jobs` columns, built-in seeds), `schemas/job.py` (`published_after_days`), `services/job_template_service.py` (new), `routers/job_templates.py` (new), `routers/jobs.py` (provenance), `agents/search_agent.py` (relative window as a preference in ranking), `frontend/src/pages/SubmitJobPage.tsx` (fix, picker), `JobDetailPage.tsx` (save), `frontend/src/pages/TemplatesPage.tsx` (new), `services/jobTemplatesApi.ts`.

## Risks

- **`{{topic}}` placeholders** in instructions need an escaping rule and a decision on what happens when a template's `preferred_channels` are later unsubscribed (recommended: warn in the picker, do not block).
- **Built-in seeds in a migration** must be idempotent and re-runnable when their text is revised (`builtin_key` + version).
- **`published_after_days`** touches the search agent's ranking prompt; coordinate with S-1.17.2's temporal ranking work, which edits the same prompt.

## Test strategy

- Service: save creates version 1, edit creates version 2 with `is_latest` moved, delete keeps history for provenance, built-ins immutable (403 on write), isolation.
- Instantiation: a template with an invalid field fails `JobCreate` validation with a clear error; `template_id` and `template_version` recorded on the job.
- Duplicate fix: `jobToFormState` carries `output_length` and `visual_analysis` (a frontend unit test, the first in the project; otherwise a Playwright assertion).
- Frontend: type-check; save → pick → submit smoke.

## First PR (S-8.6.1)

The Duplicate fix, the table and seeds, the service and routes, provenance columns, the picker and save button, tests. One PR; the relative window can split out if the search-prompt coordination is awkward.

## Open questions

1. Is `published_after_days` wanted now (it changes the ranking prompt), or should templates ship without a time window first?
2. Which five starter templates? The names above are proposals.

## Sources (fetched 2026-10-19)

Postman variable scopes; Grafana dashboard JSON `version` and version history; Perplexity Projects help page; the project's own `SubmitJobPage.tsx` and `schemas/job.py`. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
