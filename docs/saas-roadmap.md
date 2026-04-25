# Pratidhvani — SaaS Roadmap

**Status:** approved (2026-04-24). Forward-looking. **Today's posture is open-source self-host.** This document specifies the constraints today's PRs must respect so the SaaS migration is mechanical, not a rewrite.

The product context (why SaaS at all) lives in [vision.md](vision.md). Concrete features land via the roadmap in [feature-roadmap.md](feature-roadmap.md) (L5).

---

## TL;DR — Forward-compat invariants

These are the rules every PR is checked against, starting today:

1. **Every user-scoped table grows a `tenant_id` UUID column** — even if self-host installs only have one tenant per user. Default value populated at row insert from `users.tenant_id`.
2. **Every user-scoped query filters by `tenant_id`** — never just by `user_id`. The query layer wraps this in a `with_tenant_scope(query, request)` helper so it's automatic.
3. **Quotas are read from a tier table, not hard-coded.** Even on self-host where every user is `free` and the values are functionally infinite, the read path goes through the tier system.
4. **No external service is called without a tenant-scoped key.** YouTube API key, LLM API keys, etc. live in a `tenant_credentials` table eventually; today the global env var is the fallback when none exists.
5. **No cross-tenant data leaks.** A document, channel, job, Q&A, note, output, or knowledge artifact in tenant A's library is **never** retrievable from tenant B's queries — even if the global Chroma collection holds both. Metadata-filter every Chroma query by `tenant_id`.
6. **Auth events are auditable.** Every login, password reset, key rotation, billing change, connector authorization gets a row in `audit_log` from day one.

If a PR violates any of these, it's blocking SaaS regardless of how clean the feature is.

---

## 1. Tenancy model

### Hierarchy

```
tenant (1) ─── (N) workspace (1) ─── (N) user
```

**Tenant** = the billing entity. One personal user → one tenant. A team plan = one tenant with multiple users.

**Workspace** = an isolated namespace inside a tenant. Default: one workspace per tenant. Multi-workspace is a Pro+ feature (e.g. one workspace per project, or one personal + one team-shared).

**User** = an individual login. Belongs to exactly one tenant. May have access to one or more workspaces within that tenant.

### Schema

```sql
-- shipped today (single-tenant per user, but column exists)
users (
  id UUID PRIMARY KEY,
  email VARCHAR UNIQUE NOT NULL,
  password_hash VARCHAR,
  tenant_id UUID NOT NULL,        -- new: required column
  default_workspace_id UUID NOT NULL,
  tier VARCHAR DEFAULT 'free',
  created_at TIMESTAMP
);

-- new
tenants (
  id UUID PRIMARY KEY,
  name VARCHAR,
  tier VARCHAR DEFAULT 'free',    -- billing tier
  billing_customer_id VARCHAR,    -- stripe customer id
  created_at TIMESTAMP
);

workspaces (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  name VARCHAR,
  created_at TIMESTAMP
);

workspace_users (
  workspace_id UUID,
  user_id UUID,
  role VARCHAR,                   -- owner, editor, viewer
  PRIMARY KEY (workspace_id, user_id)
);
```

Every user-scoped table (`jobs`, `documents`, `channels`, `qa_exchanges`, `library_qa_exchanges`, `qa_history_exchanges`, `notes`, `outputs`, `shelves`) gets:

- `tenant_id UUID NOT NULL`
- `workspace_id UUID NOT NULL`
- `created_by UUID` (the user who created the row, distinct from owner — for team plans)

### Query helper

```python
# backend/app/utils/tenancy.py (to be created)
def with_tenant_scope(query, request):
    """Filters every query by the request's tenant + workspace."""
    tenant_id = request.state.tenant_id
    workspace_id = request.state.workspace_id
    return query.filter_by(tenant_id=tenant_id, workspace_id=workspace_id)
```

Every router using SQLAlchemy queries passes through this helper. Lint rule (or PR-bot) blocks any model query that doesn't.

### ChromaDB tenancy

ChromaDB metadata filters every query by `tenant_id`:

```python
collection.query(
    query_texts=[question],
    n_results=15,
    where={"$and": [
        {"tenant_id": request.state.tenant_id},
        {"workspace_id": request.state.workspace_id},
        # plus any feature-specific filters
    ]}
)
```

Today's queries already use `where={"video_id": {"$in": approved_set}}`. Adding `tenant_id` to the `$and` is mechanical.

---

## 2. Subscription tiers

### Tiers

| Tier | Audience | Price (placeholder) |
|------|----------|---------------------|
| **Free** | Curious individuals, evaluators | $0 |
| **Pro** | Active researchers, knowledge workers | $19/mo |
| **Studio** | Power users, content creators using L2 outputs heavily | $49/mo |
| **Team** | Small teams sharing a workspace | $99/mo per workspace, includes 5 seats |

Self-host installs are functionally Studio (no caps), but the tier column exists.

### Quotas (per month, per tenant)

| Resource | Free | Pro | Studio | Team |
|----------|------|-----|--------|------|
| Documents in library | 100 | 2,000 | 20,000 | 50,000 |
| Active jobs concurrently | 1 | 5 | 20 | 50 |
| YouTube API units | 1,000/day | 5,000/day | 50,000/day | 100,000/day |
| LLM tokens (input+output) | 100K | 2M | 20M | 50M |
| Knowledge extractions | 10 | 200 | 2,000 | 5,000 |
| Q&A exchanges | 50 | 1,000 | unlimited | unlimited |
| Outputs (books/sites/decks) — Pro+ | — | 5 | 50 | 100 |
| Saved searches with alerts | 0 | 5 | 20 | 50 |
| Output storage | — | 1 GB | 10 GB | 50 GB |
| Activity connectors enabled (L3) | 0 | 2 | 5 | 5 |

Numbers are placeholders. The point is: the tier-quota table exists from day one, even if today every user gets the Studio limits.

### Quota schema

```sql
tier_quotas (
  tier VARCHAR PRIMARY KEY,
  resource VARCHAR PRIMARY KEY,
  limit_value INTEGER NOT NULL,
  period VARCHAR DEFAULT 'monthly'  -- monthly, daily, lifetime
);

usage (
  tenant_id UUID,
  resource VARCHAR,
  period_start TIMESTAMP,
  consumed INTEGER DEFAULT 0,
  PRIMARY KEY (tenant_id, resource, period_start)
);
```

Quota check:

```python
def check_quota(tenant_id, resource, increment=1):
    tier = get_tenant_tier(tenant_id)
    limit = tier_quotas[tier][resource]
    period_start = current_period_start(tier_quotas[tier][resource].period)
    current = usage[(tenant_id, resource, period_start)].consumed
    if current + increment > limit:
        raise QuotaExceeded(resource, current, limit)
    usage.increment(tenant_id, resource, period_start, increment)
```

Wired into every quota-relevant code path: job creation (concurrent), YouTube API call (units), LLM call (tokens), knowledge extraction (count), Q&A exchange (count), output creation (count).

### Feature gating

Some features are tier-gated, not just quota-gated:

| Feature | Min tier |
|---------|----------|
| Subscription jobs | Pro |
| Library-wide Q&A | Pro |
| Q&A History meta-chat | Pro |
| Author Studio (L2) | Pro (Books) / Studio (Sites, Decks, Reels) |
| Source weights (L4) | Pro |
| Personal Brain connectors (L3) | Studio |
| Multiple workspaces | Pro |
| Public report sharing (M11) | Pro |
| Saved searches (M3) | Pro |
| BYOK (bring your own LLM key) | Pro |
| Team sharing | Team |

Gating is applied as a decorator on the router function:

```python
@require_tier("pro")
@router.post("/api/v1/library/qa")
def library_qa(...): ...
```

---

## 3. Billing

### Provider

**Stripe** for SaaS. Subscription billing for tier upgrades, metered overage for heavy users, team billing for multi-seat workspaces.

### Customer & subscription objects

- `tenants.billing_customer_id` ← Stripe `cus_*`
- `tenants.billing_subscription_id` ← Stripe `sub_*`
- Stripe webhooks land at `POST /api/v1/billing/webhook`
- Tier changes happen via webhook; the app never trusts client-side tier claims

### Metered overage (later)

- LLM tokens beyond tier limit → $X per 1M tokens
- YouTube units beyond tier limit → not metered (just blocked, since YouTube costs us nothing direct but reserves quota from our project)
- Storage beyond tier limit → $X per GB-month

### Self-host billing

Self-host has no billing. Every tenant defaults to the highest tier limits effectively (no overage, no Stripe webhooks). The billing module is feature-flagged off via `BILLING_ENABLED=false` (default for self-host).

---

## 4. Auth hardening

### Today (self-host)

- Email + password registration & login
- JWT bearer tokens
- WebSocket auth via query-string token
- No password reset, no MFA, no OAuth, no audit log

### SaaS additions (incremental)

| Feature | Phase | Notes |
|---------|-------|-------|
| Audit log | Now | Add `audit_log` table; log every login, signup, password change. Cheap to add now. |
| Email verification | SaaS launch | New users must verify email before any quota-bearing action |
| Password reset | SaaS launch | Token sent via email; rate-limited |
| OAuth (Google, GitHub) | SaaS launch | Standard PKCE flow |
| MFA (TOTP) | SaaS phase 2 | Optional per-user; required for Studio/Team owners |
| Session management | SaaS launch | List active sessions; revoke individually; "log out everywhere" |
| Account lockout | SaaS launch | After N failed login attempts; rate-limited per IP and per email |
| API keys (programmatic) | SaaS phase 2 | Pro+ feature; scoped per workspace |
| SAML SSO | Team plan launch | Enterprise feature |

### `audit_log` schema

```sql
audit_log (
  id UUID PRIMARY KEY,
  tenant_id UUID,
  user_id UUID,
  event_type VARCHAR,    -- login, logout, password_change, key_rotated, billing_changed, connector_authorized
  metadata JSON,
  ip VARCHAR,
  user_agent VARCHAR,
  created_at TIMESTAMP
);
```

---

## 5. Abuse prevention

### Rate limits

Layered:

1. **Per-IP** — at the edge / reverse proxy. 100 req/min unauth, 600 req/min auth.
2. **Per-tenant** — at the application. Tier-aware. Free: 60 req/min. Pro: 600 req/min. Studio: 6000 req/min.
3. **Per-resource** — for expensive endpoints. Library Q&A: 20/min/tenant. Knowledge extraction: 5/min/tenant. Output generation: 1/min/tenant.

Implementation: Redis-backed sliding-window counters. Lives in `backend/app/middleware/rate_limit.py` (to be created).

### Fraud detection

For SaaS:

- Free-tier abuse (mass signup, single-use): require email verification + (optionally) phone verification. Block disposable email domains.
- LLM-token-cost abuse: enforce hard tier caps; block suspicious token consumption patterns (a single user generating 10M tokens in an hour).
- Storage abuse: enforce per-tenant document and output size caps.
- Subscription abuse (signup → grab Pro features → cancel): rate-limit Pro features to first-week-of-subscription levels, then full.

### Content policy

Pratidhvani ingests user-chosen sources. Some sources may be:

- Copyrighted (most of YouTube, podcasts, books)
- Abusive / illegal (rare but possible)

Posture:

- **Self-host**: no content policy enforcement; the user is responsible for what they ingest. Document this clearly in the install README.
- **SaaS**: Terms of Service prohibit ingesting content the user has no right to research personally. We rely on YouTube's own terms for video transcripts, podcast distributors' terms for episodes, etc. We don't republish — answers are personal-research-fair-use grounded in citations to the original.
- **Public report sharing (M11)**: signed URLs expire; we honor takedown requests. Shared reports are ephemeral by design.

### DMCA / takedown process

- `legal@pratidhvani.app` (placeholder email) for takedown notices.
- 24-hour SLA for compliant requests.
- Records of takedowns logged in `audit_log` with `event_type = 'takedown'`.

---

## 6. Hosting & infrastructure

### Self-host (today)

- SQLite + Redis (Windows service or Docker) + ChromaDB (embedded, persistent) + local Whisper
- Single-machine, single-process backend, single Celery worker, single frontend dev server
- Documented in [README.md](../README.md)

### SaaS (target)

| Component | Self-host | SaaS |
|-----------|-----------|------|
| App database | SQLite | **Postgres** (Cloud SQL / RDS / managed) |
| Cache & queue | Redis (single node) | **Redis Cluster** (3+ nodes) |
| Vector DB | ChromaDB embedded | **ChromaDB managed** OR **pgvector on Postgres** (TBD; decision criteria below) |
| File storage (reports, outputs, uploaded PDFs) | Local disk | **S3 / R2 / GCS** |
| LLM | User's API keys | Anthropic / OpenAI / Google direct + BYOK option |
| Whisper | Local CPU | **Whisper API** (faster) for audio transcription |
| Frontend | Vite dev server | **Static build on a CDN** (Cloudflare / Vercel) |
| Background workers | Single Celery solo worker | **Celery cluster**, auto-scaling, per-tenant queues |
| Email | n/a | **Resend / Postmark** for transactional |
| Observability | stdout logs | **Datadog / OpenTelemetry + Grafana** |

### Vector DB decision criteria

- **ChromaDB managed** wins on: identical API to self-host, no migration needed.
- **pgvector** wins on: collocates with the app DB, simpler ops, transactional consistency with metadata.
- **Decision**: stick with ChromaDB through L1; reassess at Phase 4 when collection counts are clearer.

### Data residency

SaaS users pick a region at signup: US (default), EU, India. Each region is a separate stack with its own database, vector store, and S3 bucket. Cross-region migration is a paid concierge service for now.

---

## 7. Hosted UX

### Marketing surface

- Landing page (`marketing/`) — already in [feature-roadmap.md](feature-roadmap.md) rebrand-asset rollout
- Pricing page
- About / vision page (mirror of [vision.md](vision.md) in marketing voice)
- Docs site (mkdocs / Docusaurus / Astro Starlight reading from `docs/`)
- Status page (`status.pratidhvani.app`)
- Blog (later)

### Signup flow

1. Email + password (or OAuth)
2. Email verification
3. Pick a region
4. Pick a tier (Free is fine)
5. Optional: paste a YouTube channel URL to seed first job
6. Land on dashboard with onboarding wizard (M10)

### Billing portal

Stripe-hosted billing portal embedded inside the app. Users can:

- Upgrade / downgrade tier
- Update payment method
- Cancel subscription
- Download invoices

### Support

- In-app chat (Crisp / Intercom) for Pro+ tenants
- `support@pratidhvani.app` for everyone
- Help center (Notion / Helpcenter.io) with FAQs

---

## 8. Migration plan: self-host → SaaS

User journey for an existing self-host user who wants to migrate to SaaS:

1. Self-host UI: "Export to SaaS" button.
2. Export bundles: SQLite dump + ChromaDB snapshot + reports + outputs into a single signed `.pratidhvani-archive.tar.gz`.
3. User signs up on SaaS, picks a tier, uploads the archive at "Import from self-host".
4. Server-side: validates archive, allocates tenant, restores tables, re-embeds (or migrates Chroma directly), restores files.
5. Self-host install can stay running; SaaS becomes the primary; sync is one-time, not bidirectional.

The export schema is versioned. Self-host archives older than 6 months may need a migration step.

---

## 9. PR-time forward-compat checklist

Every PR includes (manually for now; bot-enforced later):

- [ ] If it adds a new user-scoped table, the table has `tenant_id` and `workspace_id` columns
- [ ] If it adds a new query, the query is wrapped in `with_tenant_scope`
- [ ] If it adds a new external service call, the call uses tenant-scoped credentials with global-env fallback
- [ ] If it adds a new ChromaDB query, the query filter includes `tenant_id`
- [ ] If it adds a new feature, it's documented in [feature-roadmap.md](feature-roadmap.md) with a tier (or marked as universally available)
- [ ] If it adds a quota-relevant action, it calls `check_quota` before doing the action
- [ ] If it touches auth, it logs to `audit_log`

---

## 10. Open questions

- **Pricing.** Numbers in §2 are placeholders. Need market research closer to SaaS launch.
- **Open-source license.** MIT vs Apache 2.0 vs **AGPL-3.0**. AGPL is the moat choice (prevents a third party running a competing SaaS off the code), but it's friction for some contributors. Decision pending.
- **Self-host commercial use.** Allowed under any of the three licenses. Should we add a separate commercial license tier with extra support? TBD.
- **Open-core.** Some features Pro+ on SaaS — should they be **excluded** from the OSS code (open-core), or **included but rate-limited** in the OSS code (single-binary)? Recommend single-binary; exclusion is harder to maintain.
- **EU GDPR / India DPDP.** Full data residency + right-to-be-forgotten compliance. Detailed legal review needed before EU/IN region launch.

---

## 11. Cross-references

- Vision and rationale → [vision.md](vision.md)
- Where L5 lives in the roadmap → [feature-roadmap.md](feature-roadmap.md)
- Personal-brain (L3) interacts with SaaS data residency / privacy → [personal-brain.md](personal-brain.md)
- Architecture today → [architecture.md](architecture.md)
