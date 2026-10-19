# M1 — Shelves, tags and shelf-scoped views: plan

**Board:** [E-8.1](../initiatives.md#e-81--shelves--collections-tags-and-shelf-scoped-views-m1) · **Roadmap:** [M1](../feature-roadmap.md#m1--shelves-collections--folders-) · **Research date:** 2026-10-19 · **Status:** recommendation.

## Problem

Jobs are a flat list and the library is a flat list. A user researching three topics for a year has no way to group runs into projects, to tag the documents that matter, or to ask a question across "everything on my macroeconomics shelf" without re-running a job. The roadmap sketched `shelves`, `shelf_jobs` and `document_tags`; the tier gate `shelves` already exists with nothing behind it.

## Verified current state (2026-10-18)

- No `shelves`, `shelf_jobs`, `document_tags` or `tags` table; no Alembic revision mentions them (`grep -ri shelf backend/alembic` is empty).
- `TIER_CAPABILITIES` (`services/tier_service.py`) lists `shelves` for Pro and Studio; `frontend/src/hooks/useTierCapabilities.ts` mirrors it; `frontend/src/data/tiers.ts` advertises "Shelves — group jobs into projects". The word "shelf" in the UI copy ("No volumes on your shelf yet") is editorial voice, not a feature.
- `documents` is a shared cache with per-tenant visibility in `document_visibility` ([D-063](../decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)); the library listing (`routers/library.py` `list_library_videos`) filters through `visibility_service.visible_video_ids` and supports `search`, `language`, `channel_id`, `transcript_status`, `sort`.
- Job-scoped Q&A already filters Chroma by `video_id ∈ approved set` (`chroma_service.query_collection(video_ids=…)`); library Q&A passes the tenant's visible set. A shelf scope is the same mechanism with a different set.
- Sidebar navigation is `NavGroup` / `NavItem` inside `layouts/AppLayout.tsx` with a fixed `AppTab` union in `stores/jobStore.ts`.

## Chosen approach

- **Shelves ↔ jobs many-to-many** (`shelf_jobs`), Zotero semantics: a job may sit on several shelves; deleting a shelf never deletes jobs; deleting a job removes its rows. No nesting in v1; if added later, copy Zotero's explicit "include sub-shelves" toggle rather than implicit roll-up.
- **Tags as rows, not free strings**: `tags(id, tenant_id, name, color)` with `UNIQUE(tenant_id, lower(name))` and a polymorphic `taggings(tag_id, target_type, target_id)`. Stable ids survive rename (Notion's `select` options keep their id when renamed), rename and merge are one `UPDATE` (Raindrop semantics), counts and colours are first-class. Tags are **per tenant** because documents are shared: a tag is private to the user who applied it. Colour is a fixed palette of ten named tokens in `theme.ts` (Notion's set: default, gray, brown, orange, yellow, green, blue, purple, pink, red), never a hex, never colour alone (text label always present, bordered chip, 4.5:1 contrast).
- **Shelf page** at `/shelves/:id`: the shelf's jobs and the union of their documents, reusing `VideoRow`; filters from the library page apply.
- **Shelf-scoped Q&A**: `POST /shelves/{id}/qa` resolves `SELECT document_id FROM job_documents WHERE job_id IN (shelf jobs)` ∩ `visible_video_ids(tenant)` and passes it as the existing `video_ids` filter to the library Q&A agent. The D-063 rule carries over: an empty set retrieves nothing. Exchanges are stored as `library_qa_exchanges` with a `scope_json` column so the Q&A history and the `qa_library_global` index keep working unchanged.
- **Tier gate**: `require_feature("shelves")` on the write endpoints; reads of an existing shelf stay available after a downgrade (read-only), which is the pattern the subscription page's downgrade modal already describes.

## Alternatives rejected

| Option | Why not |
|---|---|
| Tags as a JSON array column on `documents` | Documents are shared; the column would leak one user's tags to all; rename is an `UPDATE` across every row; uniqueness unenforceable in SQLite without JSON tricks. |
| One shelf per job (Raindrop's one-collection rule) | Jobs legitimately belong to several projects; many-to-many is what Zotero, Readwise Reader views and Notion relations do. |
| Nested shelves in v1 | Adds tree semantics and the "include sub-shelves" question for little first-order value. |
| A separate Chroma collection per shelf | The metadata filter already scopes retrieval; per-scope collections would duplicate embeddings, the thing the global library exists to avoid. |
| Free-text colour | Accessibility and consistency; a palette of named tokens is what every design system reviewed does. |

## Schema deltas

```
shelves(id, tenant_id, name, description, color, created_at, updated_at)        UNIQUE(tenant_id, name)
shelf_jobs(shelf_id FK, job_id FK, added_at)                                      PK(shelf_id, job_id)
tags(id, tenant_id, name, color, created_at)                                      UNIQUE(tenant_id, lower(name))
taggings(id, tag_id FK, tenant_id, target_type, target_id, created_at)            UNIQUE(tag_id, target_type, target_id); INDEX(tenant_id, target_type, target_id)
library_qa_exchanges.scope_json TEXT NULL
```

`target_type` starts as `document`; `job` and `channel` are cheap later. `taggings.tenant_id` is denormalised so every read can filter without a join.

## API deltas

```
GET/POST            /api/v1/shelves
GET/PUT/DELETE      /api/v1/shelves/{id}
POST/DELETE         /api/v1/shelves/{id}/jobs/{job_id}
GET                 /api/v1/shelves/{id}/documents          (library listing params, scoped)
POST                /api/v1/shelves/{id}/qa                  (library Q&A request shape; scope recorded)
GET                 /api/v1/jobs/{id}/shelves
GET/POST            /api/v1/tags
PUT/DELETE          /api/v1/tags/{id}                        (rename, recolour, merge via ?into=)
PUT/DELETE          /api/v1/library/videos/{id}/tags/{tag_id}
GET                 /api/v1/library/videos?tag=<tag_id>
```

All lookups include the tenant; a foreign id is a 404 (the existence-leak posture every router already uses).

## Modules touched

`models/{shelf,shelf_job,tag,tagging}.py`, one Alembic revision, `services/shelf_service.py` and `services/tag_service.py` (new, the single accessors), `routers/shelves.py` and `routers/tags.py` (new), `routers/library.py` (tag filter, tag mutations), `routers/jobs.py` (delete cascade is DB-level; `GET /jobs/{id}/shelves`), `agents/qa_agent.py` only through the existing `run_library_qa_agent(video_ids=…)` signature, `models/library_qa_exchange.py` (`scope_json`), `frontend/src/layouts/AppLayout.tsx` (Shelves group), `frontend/src/pages/ShelfPage.tsx` (new), `JobsListPage.tsx`, `JobDetailPage.tsx`, `components/library/VideoRow.tsx`, `LibraryPage.tsx` (filter rail), `theme.ts` (tag palette), `services/shelvesApi.ts` and `tagsApi.ts` (new), `hooks/useShelves.ts` (new).

## Risks

- **Scope creep on `AppTab`.** The sidebar's tab union and route map are hand-maintained; a dynamic shelf list needs the nav to accept non-enum entries. Small, but touches the layout every page shares.
- **Exchange history shape.** `scope_json` on `library_qa_exchanges` is the least invasive way to keep one history table; the history page must render the scope badge or shelf questions look like library-wide ones.
- **Large unions.** A shelf of twenty 200-video jobs is 4,000 `video_id`s in one Chroma `$in` filter; the job path already does this at 200, measure at 4,000.
- **Downgrade semantics.** Decide whether a Free user keeps read access to existing shelves (recommended) or loses the page.

## Test strategy

- Service: create, rename collision (case-insensitive), add and remove jobs, delete shelf leaves jobs, delete job removes `shelf_jobs`; tag rename keeps id; merge moves taggings and deletes the source.
- Router: tier gate (Free → 403 on write, 200 on read), cross-tenant add / list / delete / tag all 404, `?tag=` filter respects visibility.
- Q&A: scope restricts citations to the shelf's documents; an empty shelf never widens to the library (the D-063 empty-set test reused); exchange stored with `scope_json`.
- Frontend: type-check; Playwright smoke create → add job → open shelf → ask.

## First PR (S-8.1.1)

Schema (`shelves`, `shelf_jobs`), `shelf_service`, the shelves and job-shelves routes, tier gate, cascade behaviour, isolation tests. No UI, no tags, no Q&A: small enough to review in one sitting and it unblocks the UI and the Author Studio site picker (E-6.2) in parallel.

## Open questions

1. Read-only access to shelves after a tier downgrade, or hide them?
2. Should `taggings.target_type` include jobs from the start (cheap) or stay documents-only until asked?

## Sources (fetched 2026-10-19)

Zotero "Collections and Tags" help and forum; Raindrop collections and tags help; Notion property-object reference (`select` options and the ten colours); design-system tag guidance (gov.scot, Red Hat, Customer.io, Sky); NotebookLM and Perplexity Projects scoping behaviour; GDPR Article 20 (user-provided data is exportable: shelves and tags are). Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
