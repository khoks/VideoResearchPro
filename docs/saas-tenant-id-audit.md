# `tenant_id` audit + retrofit roadmap (E-5.1)

**Status:** 🔴 audit — phase 1 of E-5.1. The actual schema migration is a separate phase 2 PR per the [D-032](decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03) precedent for risky data-bearing changes.

**Audience.** Future contributors planning the multi-tenant retrofit. Operators who self-host single-tenant don't need to read this — the retrofit is forward-compat for SaaS, not a near-term schema change.

**Headline finding (2026-05-04).** The codebase is **structurally single-tenant** despite having multi-user JWT auth. No model has a `user_id` foreign key. Every user shares the same Jobs / Library / Q&A history visibility. This is a known gap inherited from the early-prototype phase and tracked here as the work item that closes it.

---

## Current state

### What works today

- **JWT auth.** `User` model exists; users can register, log in, get a JWT bearer. The dependency `app.dependencies.get_current_user` validates the JWT and returns the `User` object.
- **Auth-protected routes.** Most routers depend on `get_current_user` so unauthenticated requests get 401.

### What does NOT work

- **Per-user data scoping.** The `User` ID is never written to any other table. A user who creates a Job sees that Job — and so does every other authenticated user. The dependency layer authenticates but doesn't *authorize* per-user.

This means the running app today is functionally single-tenant: a self-host instance has one shared library that all users can see / mutate. SaaS requires this to change.

---

## Audit table

The following tables are user-scoped in concept but lack `user_id` / `tenant_id` columns today:

| Table | Concept-of-scope | Current rows | Retrofit target | Risk |
|-------|------------------|--------------|-----------------|------|
| `jobs` | Per-user research jobs | shared globally | add `tenant_id`, FK → `tenants(id)` (or for v1, `users(id)`) | medium — all queries need filter |
| `job_documents` (formerly `job_videos`) | Join table; inherits `jobs.tenant_id` | shared globally | no column — joined via `jobs` | low — derived |
| `qa_exchanges` | Per-job Q&A history | shared globally | add `tenant_id`; also denormalised so queries don't need to join | medium — all queries need filter |
| `library_qa_exchanges` | Per-user library-wide Q&A | shared globally | add `tenant_id` | medium |
| `qa_history_exchanges` | Per-user history-chat | shared globally | add `tenant_id` | medium |
| `documents` | Global library | **stays global** in v1 | optional `tenant_id` for SaaS-tier-private uploads (PDFs especially) | low for now |
| `transcript_cache` | Cache keyed on document_id | **stays global** | none — derived | low |
| `channels` (renaming → `creators` per E-1.9) | Global subscribed channels | **stays global** | optional `tenant_id` for SaaS-tier-private subscriptions | low for now |
| `users` | The auth root | already keyed by `id` | n/a — `users.id` is the value other tables FK to | n/a |
| `api_quota_log` | Global YouTube API quota | **stays global** in v1 | per-tenant in SaaS — quota gating per subscription tier | low (no near-term blocker) |

### Why some tables stay global

- **`documents`**: per the L1 multi-source vision, the library is intentionally a *globally-deduplicated* store. Two users searching for the same video share one Document row + chunks. SaaS multi-tenancy can be layered on as `tenant_visibility` (a many-to-many) rather than per-tenant copies of identical content. The MVP retrofit doesn't need to touch this.
- **`transcript_cache`**: derived from `documents.document_id`; no scope of its own.
- **`channels` / `creators`**: same — global subscribed channels are a shared resource. Per-user notification preferences would be a separate `user_subscriptions` join table, not a `channels.user_id` column.

### Tables that DO need `tenant_id` immediately when SaaS launches

The four user-scoped data tables: `jobs`, `qa_exchanges`, `library_qa_exchanges`, `qa_history_exchanges`. The cascading effect on joins:

- `job_documents` doesn't need its own `tenant_id` because it's reachable via `jobs.tenant_id`. But every `JOIN ... FROM job_documents` query will need a tenant guard either in the join or via the parent.
- Q&A tables are leaf tables in the per-user graph — they need explicit `tenant_id` for fast filtering without going through the `jobs` table.

---

## Retrofit migration shape

**Recommended: 2-phase rollout per the D-032 precedent** (E-2.6 brand identifier rename, E-1.9 channels → creators rename). Both phases ship as separate PRs.

### Phase 1: schema additive — add `tenant_id` columns

```sql
ALTER TABLE jobs ADD COLUMN tenant_id VARCHAR(36) NULL;
ALTER TABLE qa_exchanges ADD COLUMN tenant_id VARCHAR(36) NULL;
ALTER TABLE library_qa_exchanges ADD COLUMN tenant_id VARCHAR(36) NULL;
ALTER TABLE qa_history_exchanges ADD COLUMN tenant_id VARCHAR(36) NULL;

CREATE INDEX ix_jobs_tenant_id ON jobs (tenant_id);
CREATE INDEX ix_qa_exchanges_tenant_id ON qa_exchanges (tenant_id);
CREATE INDEX ix_library_qa_exchanges_tenant_id ON library_qa_exchanges (tenant_id);
CREATE INDEX ix_qa_history_exchanges_tenant_id ON qa_history_exchanges (tenant_id);
```

- `tenant_id` nullable so the migration is non-breaking on existing rows. Existing rows stay tenant-less (visible to everyone) until phase 2 backfills them.
- v1 SaaS uses `users.id` as `tenant_id` (one tenant per user). Multi-workspace teams (one user → many tenants, or many users → one tenant) ship as a follow-up — the column is already there.
- Indexes added in the same migration so phase-2 query updates have fast filters from the start.

### Phase 2: backfill + enforce — set `tenant_id` on every row, switch queries

```sql
-- Backfill: assume there's exactly one user (the self-host operator).
UPDATE jobs SET tenant_id = (SELECT id FROM users LIMIT 1)
  WHERE tenant_id IS NULL;
-- ... same for qa_exchanges / library_qa_exchanges / qa_history_exchanges
```

Plus:
- Update every router's query: `db.query(Job).filter(Job.tenant_id == current_user.id, ...)`.
- Update every `Job.create()` / `QAExchange.create()` to set `tenant_id` from the JWT.
- Add a `tenant_id NOT NULL` constraint *after* the backfill is verified (so a code bug that forgets to set it doesn't silently insert rows into "the global tenant").

### Phase 3 (future): workspace concept

When multi-user-per-workspace is needed (team SaaS tier):

```sql
CREATE TABLE tenants (
  id VARCHAR(36) PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  ...
);
CREATE TABLE tenant_users (
  tenant_id VARCHAR(36) NOT NULL,
  user_id VARCHAR(36) NOT NULL,
  role VARCHAR(20) NOT NULL,  -- owner / member / viewer
  PRIMARY KEY (tenant_id, user_id)
);
```

`tenant_id` columns on user-scoped tables become FKs to `tenants.id`. The JWT carries `current_tenant_id` (selected at login from the user's accessible tenants) instead of just `user_id`.

---

## Risk assessment

The risk is *bug-shaped*, not data-shaped. Concretely:

1. **A query forgetting the `tenant_id` filter leaks data** across tenants. Detection: a code-review checklist that every `db.query(<UserScoped>).filter(...)` includes `<UserScoped>.tenant_id == current.<...>`.
2. **A row INSERT forgetting `tenant_id` lands in "the global tenant"** (NULL). Detection: the NOT NULL constraint added in phase 2.
3. **An existing self-host instance with multiple users has data attribution ambiguity** — which existing job belongs to which user? Solution: the phase-2 backfill picks the operator's user (the first / only / explicit `OPERATOR_USER_EMAIL` config value) and stamps every existing row with that tenant. Other users see an empty library on first login post-migration; they can re-enter their data.

The MVP-acceptable failure mode is option 3: existing self-host data gets attributed to a single tenant. SaaS deployment doesn't have this problem because tenant_id is set from row creation.

---

## Cross-references

- [I-5 SaaS readiness](initiatives.md#i-5--saas-readiness-long-horizon) — parent initiative.
- [D-032 — Operator-coordinated runbook for data-bearing identifier renames](decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03) — the precedent for two-phase risky migrations.
- [`docs/saas-roadmap.md`](saas-roadmap.md) — the broader SaaS-tier shape.
- [`docs/migration-channels-to-creators.md`](migration-channels-to-creators.md) — sibling runbook (E-1.9).
- [`docs/migration-code-identifiers.md`](migration-code-identifiers.md) — sibling runbook (E-2.6).

This audit document is **phase 0** of E-5.1. Phase 1 (the additive `tenant_id` columns + indexes) is the next-up PR; phase 2 (backfill + query updates + NOT NULL enforcement) is the PR after that. Until phase 2 lands, the app remains structurally single-tenant.
