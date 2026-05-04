# Changelog

All notable changes to **Pratidhvani (प्रतिध्वनि)** — formerly *VideoResearchPro* — are recorded here.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Releases are not yet tagged; entries are ordered by PR merge date, newest first. Once the project cuts its first semver tag, this file will shift to dated release sections.

For the *why* behind any entry, follow the linked PR. For the active roadmap, see [docs/feature-roadmap.md](docs/feature-roadmap.md).

---

## Unreleased

### I-5 final reconciliation: design-complete framing for E-5.3 / E-5.7 / E-5.8 / E-5.9

- **Closes the open coordination gap** between [`docs/initiatives.md`](docs/initiatives.md) and [`docs/saas-roadmap.md`](docs/saas-roadmap.md) for the four code-deferred epics (Stripe, Data residency, Hosting, Hosted UX). Each saas-roadmap section now opens with a status note that:
  - Cross-links the relevant `E-5.x` task ID in `initiatives.md`.
  - Explains why the epic is design-complete-but-code-deferred (no meaningful code work for a self-host install — Stripe billing for a single-user install? Region-stack provisioning for a single-machine install?).
  - Disambiguates "operations work" (E-5.8) from "code work" (which sits inside the L1/L2 epics that touch Postgres compatibility, S3 storage, etc.).
- **`docs/initiatives.md`** — I-5 header now opens with a status table summarizing what's shipped (E-5.1 fully closed; E-5.2/.4/.5/.6 foundations) vs what's design-complete-code-deferred (E-5.3/.7/.8/.9). Each ⚪ epic's entry has a "Design-complete 2026-05-04" note pointing to its saas-roadmap.md home.
- **`docs/feature-roadmap.md`** — L5 status block rewritten to enumerate all five code-shippable I-5 epics with their current status; remaining four design-complete epics called out as such with rationale.
- No code change.

### E-5.6 foundation: per-user BYOK LLM credentials (Studio-gated)

- **Foundation for [E-5.6 background-job isolation](docs/initiatives.md#e-56--background-job-isolation).** Per-user, per-provider API keys with encryption-at-rest. Studio-tier users can route their LLM calls to their own provider account. Cross-cutting LLM resolution-path integration (T-5.6.4) deferred to a separate PR since it touches ~19 use cases and the current agent layer has no user-context plumbing.
- **`backend/app/models/user_credential.py`** + Alembic `b9c0d1e2f3a4_byok_credentials.py` — `user_credentials(id, user_id, provider, encrypted_secret, label, created_at, updated_at)` with `(user_id, provider)` unique constraint and `user_id` index.
- **`backend/app/services/byok_service.py`** — `cryptography.fernet.Fernet` encrypt/decrypt keyed off `BYOK_ENCRYPTION_KEY` env var. Plaintext is **never** persisted — only the Fernet ciphertext (URL-safe base64). `set_credential` (upsert), `get_credential`, `list_for_user`, `delete_credential`. Provider validation against `SUPPORTED_PROVIDERS = {openai, anthropic, google, local}` (matches `llm_routing.py`). **Encryption-key rotation tolerance:** `get_credential` returns `None` (with warning) when ciphertext is undecryptable, so consumers fall back to install-wide env-var keys rather than crashing.
- **`backend/app/routers/credentials.py`** — REST endpoints under `/api/v1/auth/credentials/*`, all gated on `require_feature("byok_llm_keys")` (Studio-only). `GET /` lists metadata (not the plaintext); `PUT /{provider}` upserts; `DELETE /{provider}` removes; `GET /providers` returns the supported set.
- **`BYOK_ENCRYPTION_KEY`** config — when unset, a process-local Fernet key is generated at startup with a loud warning (stored credentials become unrecoverable on restart). Operators MUST set this in production. Generate via `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- **20 new tests** in `test_services/test_byok_service.py` (12) and `test_routers/test_credentials.py` (8). Covers encryption round-trip + non-determinism, upsert semantics, cross-user isolation, key-rotation tolerance, auth + tier gating, plaintext-not-leaked invariant on every response. Backend suite 835 → 855.

### E-5.5 phase 1: rate-limit middleware (per-route + per-tier)

- **Closes the largest practical-value chunk of [E-5.5 abuse prevention](docs/initiatives.md#e-55--abuse-prevention).** Three-tier rate-limiting strategy: sensitive endpoints (login, password-reset, register) → per-IP credential-stuffing defence; authenticated routes → per-user tier-aware bucket (60/600/6000 req/min for Free/Pro/Studio); unauthenticated GETs → per-IP fallback.
- **`backend/app/services/rate_limit_service.py`** (new) — sliding-window counter via in-memory dict + `threading.Lock`. `RateLimit(requests, window_sec)` config + `check_and_consume(key, limit) -> (allowed, count, retry_after_sec)`. Auto-prunes expired buckets. In-memory by design for single-process self-host; one-function swap to Redis-backed buckets for multi-worker SaaS deployment (T-5.5.4).
- **`backend/app/middleware/rate_limit.py`** (new) — FastAPI `BaseHTTPMiddleware`. JWT pre-parse extracts the user_id without a DB lookup so the bucket key is stable. Returns `429 Too Many Requests` with `Retry-After` (seconds), `X-RateLimit-Limit`, `X-RateLimit-Remaining` headers; OK responses also carry the same headers so well-behaved clients can back off proactively.
- **Test posture** — `RATE_LIMIT_ENABLED=False` set globally in `conftest.py` so existing tests don't suddenly hit 429s; individual rate-limit tests opt back in via `monkeypatch`. Bucket state cleared between tests via `rate_limit_service.reset()` in the `db` fixture teardown.
- **Config knobs** — `RATE_LIMIT_ENABLED` (default True), `RATE_LIMIT_PER_MIN_FREE` (60), `RATE_LIMIT_PER_MIN_PRO` (600), `RATE_LIMIT_PER_MIN_STUDIO` (6000), `RATE_LIMIT_PER_MIN_UNAUTH` (100), `RATE_LIMIT_LOGIN_PER_MIN` (10), `RATE_LIMIT_RESET_PER_MIN` (5), `RATE_LIMIT_REGISTER_PER_MIN` (5).
- **12 new tests** in `tests/test_services/test_rate_limit.py` covering rate-limit dataclass validation, sliding-window correctness (consecutive calls + bucket roll-over + independent keys + retry-after monotonicity), middleware integration on each sensitive endpoint, per-user bucket enforcement, response headers, kill-switch pass-through. Backend suite 823 → 835.

### E-5.4 phase 1: audit log + account lockout + password reset

- **Defensive auth primitives.** Closes the largest practical-value chunk of [E-5.4 auth hardening](docs/initiatives.md#e-54--auth-hardening): credential-stuffing defence (lockout), self-service recovery (password reset), observability (audit log). OAuth and MFA deferred to separate PRs since each has substantial provider-specific complexity.
- **`backend/app/models/audit_log.py`** + **`backend/app/services/audit_service.py`** — append-only event log with canonical `Event` enum: `USER_REGISTERED` / `LOGIN_SUCCESS` / `LOGIN_FAILURE` / `LOGIN_LOCKED_OUT` / `ACCOUNT_LOCKED` / `PASSWORD_RESET_REQUESTED` / `PASSWORD_RESET_COMPLETED` / `PASSWORD_RESET_INVALID_TOKEN`. Records IP (with `X-Forwarded-For` first-hop), user-agent (truncated to 512 chars), and structured metadata. Failures are logged but never propagate — auditing must not break the call site (mirrors quota_service pattern). `GET /api/v1/auth/audit-log` returns the current user's events newest-first; capped at 500/page.
- **Account lockout** — `users.failed_login_attempts INT NOT NULL DEFAULT 0` + `users.locked_until DATETIME NULL` columns added. After `LOCKOUT_FAILURE_THRESHOLD` (default 5) failed logins the account locks for `LOCKOUT_DURATION_MIN` (default 15) minutes. Successful login resets both columns. **Unknown emails do NOT create User rows** — critical defence so an attacker can't lock arbitrary accounts via brute-forced email addresses.
- **`authenticate_user_v2`** returns a structured `(user, AuthOutcome)` tuple (`SUCCESS` / `INVALID_CREDENTIALS` / `LOCKED_OUT`) so the router can audit lockouts separately from regular invalid-credential failures while still serving a generic 401 to the attacker. Legacy `authenticate_user` thin-wrapper preserved for back-compat.
- **Constant-time decoy hash** — `_DUMMY_PWD_HASH` is verified against the input password when the email doesn't exist, keeping response-time roughly comparable to a real auth so timing leaks don't reveal account existence.
- **Password reset** — new `password_reset_tokens` table (single-use, SHA-256 of the raw secret stored; the secret itself is never persisted). `POST /api/v1/auth/password-reset/request` returns 200 unconditionally (never leaks email existence); on self-host returns the secret in `debug_secret` + logs it so operators can hand off out-of-band when SMTP is unconfigured. `POST /api/v1/auth/password-reset/confirm` rotates the password + clears any active lockout. Tokens expire after `PASSWORD_RESET_TOKEN_TTL_MIN` (default 30) minutes.
- **Config additions** — `LOCKOUT_FAILURE_THRESHOLD`, `LOCKOUT_DURATION_MIN`, `PASSWORD_RESET_TOKEN_TTL_MIN`. Set `LOCKOUT_FAILURE_THRESHOLD=0` to disable lockout (not recommended in production).
- **Alembic migration `a8b9c0d1e2f3_auth_hardening.py`** — additive: creates `audit_log` (4 indexes: tenant_id / user_id / event / created_at), creates `password_reset_tokens` (2 indexes), adds 2 columns to `users` with server defaults. Reversible.
- **22 new tests** in `test_routers/test_auth_hardening.py` covering lockout threshold + reset on success + decoy-no-user-row, audit-log emission on every event including unknown-email failure, password-reset full flow + single-use enforcement + expiry + lockout-clear semantics. Backend suite 801 → 823.

### E-5.2 foundation: subscription tier enum + feature-gating utility

- **Foundation for SaaS tier gating.** Adds `users.tier String(16)` column (`server_default='free'`) via Alembic migration `f7a8b9c0d1e2_add_user_tier.py`. Self-host installs default everyone to `free` and operators upgrade via SQL; SaaS deployment will set this from the billing service.
- **`backend/app/services/tier_service.py`** — `Tier` enum (`FREE` < `PRO` < `STUDIO`), `TIER_CAPABILITIES` table per-tier (`youtube_units_per_day`, `llm_tokens_per_day`, `document_count_cap`, `features` frozenset), `require_tier(min_tier)` and `require_feature(name)` FastAPI dependency factories that raise 403 on insufficient tier, plus `get_user_tier`, `has_feature`, `quota_limit`, `capabilities_for` helpers.
- **Defense-in-depth on tier resolution** — `get_user_tier` accepts unknown / null / mixed-case / whitespace-padded strings and degrades to `Tier.FREE` rather than crashing. Legacy rows from before the migration (where `tier` IS NULL) still get a sensible default.
- **`docs/saas-roadmap.md`** — §2 Subscription tiers section updated with the foundation-shipped status note clarifying what landed (schema + utility) vs what's still ⚪ (runtime quota enforcement, deferred to E-5.5).
- **24 new tests** in `backend/tests/test_services/test_tier_service.py` — enum ordering, user→tier resolution defaults, capability table consistency invariants (quotas monotonically non-decreasing across tiers; features form supersets), `require_tier` 403 + pass-through paths, `require_feature` 403 + pass-through paths, User model defaults. Backend suite 777 → 801.
- **No endpoint gating shipped yet** — the dependency factories are wired but no production routes call them today. Author Studio (L2) and BYOK LLM keys (E-5.6) will be the first consumers when those ship.

### E-5.1 fully closed: phase 2c NOT NULL runbook + migration

- **Closes E-5.1 entirely.** Final phase ships the [`docs/migration-tenant-id-not-null.md`](docs/migration-tenant-id-not-null.md) operator runbook + the Alembic migration file `backend/alembic/versions/e6f7a8b9c0d1_tenant_id_not_null.py` that flips `tenant_id` from NULLABLE → NOT NULL on the four user-scoped tables.
- **Operator-coordinated** per [D-032](docs/decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03) / [D-038](docs/decisions.md#d-038--tenancy-retrofit-ships-in-four-phases-audit--additive--backfillwrites--reads--not-null-2026-05-04). The migration ships but is not auto-applied at startup; operators run `alembic upgrade head` after the runbook's pre-flight (verify zero NULL rows on each table / backup the DB / stop writers). Sibling pattern to `docs/migration-channels-to-creators.md` and `docs/migration-code-identifiers.md`.
- **Runbook covers** — pre-flight verification SQL, NULL-row resolution playbook (re-run idempotent backfill or manual attribution), migration application, post-migration smoke test, two rollback paths (file restore vs Alembic downgrade), future-proofing for SaaS multi-tenant deployment.
- **ORM tightening** (`Mapped[str | None]` → `Mapped[str]`) deferred to a calm follow-up PR per the runbook's §5 — the schema-level constraint is what enforces correctness; the typing hint is purely a developer-experience win that doesn't need to ship in lockstep.
- After this PR, **I-5 / E-5.1 is fully closed**; remaining I-5 work moves to E-5.2 (subscription tiers), E-5.3 (Stripe), E-5.4 (auth hardening), E-5.5 (abuse prevention), E-5.6 (background-job isolation), E-5.7 (data residency), E-5.8 (hosting), E-5.9 (hosted UX).

### E-5.1 phase 2b: read-side tenant_id filtering + cross-tenant 404 (PR #152)

- **Closes the read-side half of E-5.1.** Every user-facing GET that returns user-scoped rows now filters by the authenticated user's `tenant_id`. Other users' rows are invisible (404 not 403, to avoid leaking existence) per the audit doc's threat model.
- **`backend/app/services/job_service.py`** — `get_job(db, job_id, tenant_id=None)` and `get_jobs(db, ..., tenant_id=None)` accept an optional tenant filter. `None` preserves legacy/Celery-worker call paths; routers thread `tenant_id=current_user.id` from `Depends(get_current_user)`.
- **Routers updated** — `jobs.py` (list / get / cancel / delete / videos / approve), `qa.py` (job-scoped Q&A history + report), `library.py` (library Q&A history), `qa_history.py` (history-chat list). All four routers now consistently scope reads to the authenticated user.
- **Migration ID fix.** Earlier phase-1 migration `a1b2c3d4e5f6_add_tenant_id_columns.py` collided with the existing `a1b2c3d4e5f6_add_transcript_cache_table.py`. Renamed to `d5e6f7a8b9c0` (also rejected `c1d2e3f4a5b6` due to a second collision); updated revision string + downstream `b2c3d4e5f6a7_backfill_tenant_id.py`'s `down_revision` pointer to chain correctly.
- **Tests** — 4 new in `test_tenant_id_columns.py` covering cross-tenant isolation (list filters / 404 on other-user's job / library Q&A scoped / history-chat scoped). Updated `_make_completed_job` and `_make_completed_topic_job` test helpers to accept `tenant_id` so existing tests still pass after the read-side filter took effect.

### E-5.1 phase 2a: backfill migration + write-side tenant_id stamping (PR #151)

- **Backfill migration `b2c3d4e5f6a7_backfill_tenant_id.py`** — sets `tenant_id = (SELECT id FROM users ORDER BY created_at LIMIT 1)` on the four user-scoped tables WHERE `tenant_id IS NULL`. Idempotent (the WHERE clause makes it a no-op on already-populated rows). Self-host operators with one user → all legacy rows attribute correctly. Multi-user installations attribute legacy rows to the first user; T-5.1.3 will offer a re-attribution step when E-5.1 phase 3 lands.
- **Write-side stamping** — every endpoint that creates a `Job` / `QAExchange` / `LibraryQAExchange` / `QAHistoryExchange` now stamps `tenant_id=current_user.id` at the call site. Touches `routers/jobs.py` (topic / channel / subscription job creation), `routers/channels.py` (subscribe → subscription Job dispatch), `routers/qa.py` (job Q&A exchange), `routers/library.py` (library Q&A exchange), `routers/qa_history.py` (history-chat exchange).
- **Tests** — 6 new in `test_tenant_id_columns.py` covering set-explicit (4 tables), filter-by-tenant_id, write-side stamping via the topic-job endpoint and the subscribe endpoint.

### E-5.1 phase 1: additive tenant_id columns + indexes (PR #150)

- **Alembic migration `d5e6f7a8b9c0_add_tenant_id_columns.py`** (originally drafted as `a1b2c3d4e5f6`, renamed after collision with the transcript-cache migration). Adds NULLABLE `tenant_id String(36)` column + index to four user-scoped tables: `jobs`, `qa_exchanges`, `library_qa_exchanges`, `qa_history_exchanges`. Phase-1 is purely additive — no existing INSERT or SELECT path changes shape; legacy code keeps working unchanged.
- **ORM model updates** — `app/models/job.py`, `qa_exchange.py`, `library_qa_exchange.py`, `qa_history_exchange.py` each add `tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)`. SQLAlchemy 2.x typed-mapping syntax matches existing column shapes.
- **Tests** — 5 new in `test_tenant_id_columns.py` covering NULL-default behavior on legacy-style INSERTs (4 tables) and value-acceptance.
- Per the [E-5.1 audit doc](docs/saas-tenant-id-audit.md), this is the safe additive step before backfill / writes / reads land in subsequent phases. Identical risk profile to D-032's two-phase precedent.

### E-5.1 phase 0: tenant_id audit doc — codebase is structurally single-tenant (PR #149)

- **`docs/saas-tenant-id-audit.md`** — comprehensive audit of multi-tenancy gaps. Headline finding: despite shipping JWT auth + email/password registration, the codebase has **zero tenant_id columns** on user-scoped tables. All routes read `current_user` from JWT but never filter rows by user. A user logging in sees every other user's jobs / Q&A history / library exchanges.
- **Audit covers** — four user-scoped tables (`jobs`, `qa_exchanges`, `library_qa_exchanges`, `qa_history_exchanges`), the threat model (existence-leak via cross-tenant 403 vs. 404), the safe-retrofit shape (4-phase: 0 audit → 1 additive → 2a backfill+writes → 2b reads → 2c NOT NULL), the deferred-to-operator phase 2c rationale (NOT NULL constraint requires zero-NULL guarantee, which only the operator can prove for their data).
- Flips **E-5.1 ⚪ → 🟡** in `docs/initiatives.md` with task tree T-5.1.0 (audit, this PR) / T-5.1.1 (phase 1 additive) / T-5.1.2 (phase 2a/b writes+reads) / T-5.1.3 (phase 2c NOT NULL, deferred to operator runbook).

### S-1.5.9 + S-1.5.10: BYOK Twitter / X v2 — bearer-token connector + capability flag (PR #148)

- **Closes S-1.5.9 + S-1.5.10.** Per [D-009](docs/decisions.md#d-009--twitter-x-stays-byok-paid-api--explicitly-opt-in-2026-04-25), Twitter / X integration is **explicitly opt-in** — operators must register a Twitter API v2 app and provide a Bearer token. Default install yields zero Twitter capability, no errors.
- **`backend/app/sources/twitter/`** — new `TwitterClient` (Twitter API v2 bearer-auth: `Authorization: Bearer <TWITTER_BEARER_TOKEN>`, `/2/tweets/search/recent`, `/2/users/by/username/{handle}`, `/2/users/{id}/tweets`) + `TwitterConnector` subclassing the paste-mode `TweetConnector`. Subclass overrides `search()`, `list_creator_items()`, `resolve_creator_id()`; inherits paste-mode `fetch_text` so paste-only operators still get the `tweet` source type without a Bearer token.
- **`backend/app/sources/__init__.py` re-registers `tweet` after `paste_url`** so the search-having `TwitterConnector` wins last-write-wins. Operators with `TWITTER_BEARER_TOKEN` set get search; operators without it get paste-mode TweetConnector exclusively.
- **`/api/v1/health` capability flags** (S-1.5.10) — health response now includes a `capabilities` block with `twitter_search_enabled` / `article_search_enabled` / `playwright_fallback_enabled` / `whisper_transcribe_enabled` booleans. Frontend reads these to enable/disable surfaces without inspecting backend env state directly.
- **Config** — `TWITTER_BEARER_TOKEN`, `TWITTER_API_BASE`, `TWITTER_USER_AGENT`, `TWITTER_RATE_LIMIT_RPM`, `TWITTER_REPLY_DEPTH_DEFAULT`. Defaults are conservative; operators with paid plans can scale up. `.env.example` and `CLAUDE.md` env-var table updated.
- **Tests** — 28 new (26 connector / 2 health-capability) in `test_twitter_connector.py` and `test_health.py`. Backend suite 749 → 777.

### I-1 fully closed: channels → creators rename runbook (PR #146)

- **Closes E-1.9** (and with it, **closes I-1 Multi-source ingest** entirely). Python-level alias ships now; SQL table rename deferred to runbook per D-032 precedent.
- **`backend/app/models/creator.py`** — new module re-exporting the `Channel` ORM class as `Creator`. Both names resolve to the same SQLAlchemy class while the underlying table is still `channels`. New code uses `Creator`; existing code using `Channel` keeps working indefinitely.
- **`docs/migration-channels-to-creators.md`** — operator-coordinated runbook for the SQL-level rename (`channels` table → `creators`, `documents.channel_id` FK → `creator_id` via Alembic batch_alter_table). Same shape as `docs/migration-code-identifiers.md`. Phase 2 of E-1.9 (a small future PR) flips `__tablename__` to `creators` after operators have run the runbook.

### E-1.6 closed: article search + RSS — Brave + RSS feed discovery (PR #145)

- **Closes E-1.6 fully**. T-1.6.2 (Brave Search integration), T-1.6.3 (RSS feed iteration), T-1.6.5 (e2e wiring) all in this PR; T-1.6.4 (approval card) was already shipped in PR #144's S-1.5.8 wave; T-1.6.6 (Playwright fallback) shipped earlier in PR #141; T-1.6.1 (primitives) shipped in PR #135.
- **`backend/app/sources/article/`** — new package overriding the paste-only base from `paste_url`. `ArticleClient` wraps Brave Search (`X-Subscription-Token` auth, free-tier-friendly per D-037) + RSS feed fetcher (httpx + feedparser). `ArticleConnector` subclasses `_PasteArticleConnector`, inherits paste-mode `fetch_text`, overrides `search()` (Brave) + `list_creator_items()` (RSS).
- **`search()` returns `[]` gracefully when `BRAVE_SEARCH_API_KEY` is unset** — operators who haven't opted in still get working paste + RSS without per-call errors. Topic jobs that include `source_types=['article']` don't fail; they yield zero search candidates until the key is configured.
- 19 new tests; backend suite 715 → 734.

### S-1.5.8: Mode B paste-mode end-to-end — 5 paste source types + endpoint (PR #144)

- **Twelfth source type** plugs into the polymorphic plumbing. Closes S-1.5.8 (Manual-paste mode for FB / IG / LI / X-without-paid + generic articles) and validates the polymorphic plumbing claim **12 times** end-to-end.
- **Per-platform discriminators** per [D-036](docs/decisions.md#d-036--paste-mode-emits-five-distinct-source_type-discriminators-not-a-single-paste-2026-05-03) — five distinct `source_type` values (`article` / `fb_post` / `ig_post` / `li_post` / `tweet`) sharing a single `_PasteURLBaseConnector` superclass. All five delegate to `article_extraction.extract_text` for fetch + Playwright-fallback.
- **`app/services/paste_url_resolver.py`** — `resolve_source_type(url)` host-based router with subdomain-prefix tolerance.
- **`POST /api/v1/library/paste-urls`** — accepts `{urls: [...]}`, resolves source_type per URL, dispatches through connector registry, embeds. Per-URL result dicts let frontend show per-URL state; 100-URL cap.
- **Frontend** — 5 new SOURCE_CONFIGS entries with platform-specific glyphs (ArticleGlyph / FBGlyph / IGGlyph / LIGlyph / XGlyph). Mapped-type registry forced compile-time enforcement.
- 51 new tests; backend suite 664 → 715.

### M-1.8: PDF / e-book connector + upload endpoint (PR #142)

- **Seventh source type** plugs into the polymorphic plumbing — and the first with no discovery surface (PDFs come from upload, not search). Closes E-1.8 / Milestone M-1.8.
- **`backend/app/sources/pdf/`** — new package. `PDFConnector.search()` and `list_creator_items()` raise `NotImplementedError` per [D-035](docs/decisions.md#d-035--connectors-with-no-discovery-surface-raise-notimplementederror-dispatcher-treats-as-zero-candidates-2026-05-03); the dispatcher's existing try-block handles them gracefully (validates the PDF design assumption baked into D-026 since 2026-05-02). `fetch_text` reads upload-stored bytes, runs through PyMuPDF, emits one segment per page with per-page `extra={kind:"page", page:N, comment_id:"pdf:<hash>:p<N>", comment_url:"<url>#page=<N>"}`. Tables extracted via `find_tables()` and rendered inline.
- **Identity** per [D-034](docs/decisions.md#d-034--pdf-source-type-identity-uses-first-64kb-sha-256-not-full-file-hash-2026-05-03) — `source_id = f"pdf:{first_64kb_sha256}"`. Fast for very large PDFs (academic books); dedup-stable across trailer-metadata variation; idempotent re-upload returns existing Document with `deduped=True`.
- **`POST /api/v1/library/upload-pdf`** — multipart upload endpoint. Hashes, persists raw bytes at `PDF_UPLOAD_DIR/<hash>.pdf`, creates Document, runs `fetch_text` inline, chunks via the same `_build_video_metadata` + `chunk_transcript` path every other source type uses, embeds into global Chroma. File-size guard at `PDF_MAX_BYTES` (default 100MB). **`GET /api/v1/library/pdf/{digest}.pdf`** serves bytes back so per-page `#page=<N>` deep-link citations work in standard PDF viewers.
- **Frontend** — `pdf` in `SourceMetadata` (`pageCount`, `wordCount`, `uploadedAt`); `PDFGlyph` SVG; chip layout; `videoToApprovalProps` mapper; `<CitationLink>` renderCitation case (`<doc title> · p. <N>`); `Reference.page_number` field.
- **Backend** — `_chunk_to_reference` branch for `pdf` extracts page number from `comment_id` (`pdf:<hash>:p<N>`), prefers `comment_url` (with `#page=<N>` fragment) for permalink, renders `timestamp_display` as `p. <N>`.
- **Tests** — 19 new in `test_pdf_connector.py` using real PyMuPDF (in-memory PDFs built via fitz's writer; no fixture binaries). Backend suite 645 → 664.
- **Out of scope (E-1.8 follow-ups)**: frontend file-upload UI, OCR for image-only PDFs, per-page Q&A reranking.

### T-1.6.6: Playwright fallback for article extraction (PR #141)

- **Closes E-1.6 primitives layer fully.** Replaces T-1.6.1's structurally-present `_playwright_fallback` stub with real headless-Chromium SPA extraction. Lazy-imports `playwright.sync_api`, navigates with `wait_until="networkidle"` for hydration, grabs rendered HTML, re-feeds through trafilatura, tags result `source='playwright'`.
- **Opt-in install** via new `backend/requirements-spa.txt`: `pip install -r backend/requirements-spa.txt && playwright install chromium`, then `ARTICLE_PLAYWRIGHT_ENABLED=True` in `.env`. Default install (just `requirements.txt`) keeps Pratidhvani lean.
- **Lazy import + multi-tier fallback**: when `playwright` isn't on the path / Chromium isn't installed / hydration times out / page errors / any unexpected exception → returns None with INFO log. Never crashes the orchestrator. New `ARTICLE_PLAYWRIGHT_TIMEOUT_SEC` (default 30s) caps the goto+content loop.
- **Unblocks S-1.5.8 T-1.5.8.5** (FB / IG paste) — FB / IG are the canonical SPA-shell pages where this fallback is load-bearing.
- 8 new tests using `mock_playwright_module` fixture (sys.modules injection so tests don't require Chromium installed). Backend suite 637 → 645.

### M-1.7: Podcast connector e2e (PR #140)

- **Sixth source type** plugs into the polymorphic plumbing without core changes. Closes E-1.7 / Milestone M-1.7. Resolves [OQ-4 per D-033](docs/decisions.md#d-033--whisper-as-service-for-podcasts-reuse-existing-openai-whisper-path-resolves-oq-4-2026-05-03) — reuse existing OpenAI Whisper path rather than separate service.
- **`backend/app/sources/podcast/`** — `PodcastClient` (iTunes Search + RSS fetch + audio download), `PodcastConnector` (two-tier discovery: iTunes search → per-show RSS → recent K episodes), `flatten` (SRT / VTT / Whisper-segment normalisation + episode-extra-attach), `connector` (full `BaseConnector` impl).
- **Discovery** — iTunes Search API (free, no auth) for show-level matches + per-show RSS feeds via `feedparser` for episode-level candidates. `PODCAST_SEARCH_TOP_N_SHOWS × PODCAST_EPISODES_PER_SHOW = 15` candidates per topic search by default.
- **Text extraction** — preferred path is in-feed `<podcast:transcript>` SRT or VTT (Podcast Index 2.0 extension). Whisper fallback when no transcript: download enclosure to temp file, reuse `_whisper_transcribe_with_retry` helper from `youtube_service`. Gated on `OPENAI_API_KEY` like YouTube fallback.
- **Identity** — `source_id = f"podcast:{episode_guid}"`. GUIDs are required by RSS-2.0 and stable across CDN URL rotations. `creator_external_id = feed URL` (canonical show id).
- **Per-segment provenance** — every segment carries `comment_url = episode_url + #t=<sec>` so podcast players that honour the fragment (Overcast, Pocket Casts, Apple Podcasts iOS 17+) deep-link citations to the cited timestamp.
- **`_entry_field(entry, key)` helper** unifies feedparser's `FeedParserDict` (attr access) with plain `dict` (key access) so the connector works against test fixtures + production feeds alike.
- **Frontend** — `podcast_episode` SourceMetadata variant + SOURCE_CONFIGS entry + PodcastGlyph SVG + videoToApprovalProps + `<CitationLink>` renderCitation case (`<episode title> · <show name> · <timestamp>`).
- **Tests** — 44 new in `test_podcast_connector.py`. All mocks; no network or Whisper API calls. Backend suite 593 → 637.
- **Adds `feedparser>=6.0.10`** to requirements.txt.

### I-2 closed: code-identifier-rename runbook (PR #137)

- **`docs/migration-code-identifiers.md`** — operator-driven safe-execution runbook for the data-bearing renames (`CHROMA_GLOBAL_COLLECTION_NAME`, `DATABASE_URL`). Three sections: §A Chroma collection rename with idempotent paginated backfill script + post-migration verification + rollback; §B SQLite file rename with backup-and-rename + verification + rollback; §C optional GitHub repo rename (outside-codebase, GitHub auto-redirects). Promise: never destroys data; every step reversible up to the operator deleting the legacy backup.
- **E-2.6 🟡 → 🟢** with all 6 tasks closed (T-2.6.1 / .2 / .3 / .4 marked operator-coordinated with the runbook as the safe path; T-2.6.5 already shipped PR #97; T-2.6.6 the runbook itself). Combined with E-2.5 from PR #136, **I-2 (Brand & visual identity rollout) flips 🟡 → 🟢 fully closed** — all 6 epics shipped (tokens / primitives / page migration / sidebar / marketing / rename pass).

### E-2.5 closed: marketing landing page sections (PR #136)

- **`marketing/src/pages/index.astro`** — replaced T-2.5.1 scaffold with the full warm-editorial landing page. Seven sections covering hero (Devanagari + Latin lockup, tagline, dual CTA), Wikipedia-vs-Pratidhvani thesis (two-column with editorial pull-quote), source-types matrix (9 cards covering 5 live + 4 upcoming source types with status pills), how-it-works (5 numbered steps with gold-accent rule), self-host install (requirements + quick-start shell block), waitlist (disabled CTA), footer (brand mark + nav + tagline).
- Mobile-responsive (two-column collapses at <720px; source-grid auto-fits at minmax(240px, 1fr)). Inherits warm-editorial palette + typography from `BaseLayout.astro` (paper bg, oxblood accent, forest-teal status, vintage gold, Fraunces / Source Serif 4 / Inter / Tiro Devanagari Hindi).
- Astro builds 1 page in ~1.5s with no errors. Closes T-2.5.2 → T-2.5.8; with T-2.5.1 already shipped PR #98, **E-2.5 fully closed**.

### Article extraction primitives (PR #135 — E-1.6 T-1.6.1)

- **New `backend/app/services/article_extraction/` module.** `ExtractionResult` typed dataclass (text, title, author, published_at, language, word_count, source ∈ {trafilatura, playwright, manual}, extra dict) + `extract_text(url)` hybrid orchestrator: httpx fetch (15s read / 5s connect, polite User-Agent, follow_redirects) → trafilatura primary (`output_format='json'`, `with_metadata=true`, `favor_precision=true`) → Playwright fallback stub → best-effort fallback gated by `HARD_FLOOR_WORDS=20` so nav-chrome / error-page noise doesn't pollute the library.
- **Playwright fallback is structurally a stub today** — returns `None` with INFO log. Rationale: Playwright pulls ~150MB of Chromium binaries and the opt-in install pattern (`pratidhvani[spa]` extra) belongs alongside the orchestrator code that triggers it. The stub is structured so the follow-up swaps just the function body.
- **Fail-soft contract**: any extraction failure (HTTP error / network error / malformed HTML / trafilatura raises / non-JSON output) returns None — never bubbles. Caller treats None as "document unavailable".
- **20 unit tests** in `test_article_extraction.py` covering typical longform article path, paywall-stub best-effort fallback, SPA-shell + nav-page → None, HTTP 4xx/5xx + connection errors + invalid URL inputs, defensive trafilatura failure modes, multi-format date parsing (YYYY-MM-DD + full ISO-with-tz + unparseable), `ExtractionResult` shape including manual-paste source. Backend suite 573 → 593.
- **Adds `trafilatura>=1.12.0` and `httpx>=0.27.0` to requirements.txt** (httpx was transitive; now explicit). Unblocks S-1.5.8 (Mode B paste-mode) without re-implementing trafilatura wrapping.
- **E-1.6 status flipped 🔵 → 🟡** — primitives shipped; full UX (T-1.6.2 search-engine, T-1.6.3 RSS, T-1.6.4 approval card, T-1.6.5 e2e) stays deferred per D-024 until after M-1.7.

### S-1.5.12 closed: per-segment chunker rework + LLM prompt update (PR #134)

- **Per-segment chunker rework (T-1.5.12.2).** `_Seg` tuple shape changed from `(text, start, end)` to `(text, start, end, extra)`. Sentence-expansion propagates parent `extra` to every sub-segment (all sentences within one segment share the same provenance). New `_emit_chunk(items)` helper applies a **dominant-segment heuristic** — pick the segment in the chunk with the most tokens and promote its `comment_id` / `comment_url` / `author` / `kind` / `depth` to chunk-level metadata. Rationale documented in helper docstring: most chunks contain a single segment so dominant is trivial; for chunks straddling replies the longer reply contributes the bulk of the searchable text and is the more meaningful citation target.
- Chunk metadata now carries `comment_id` / `comment_url` / `segment_author` / `segment_kind` / `segment_depth`. The Q&A agent's existing per-source `_chunk_to_reference` branches already read `comment_id` / `comment_url` from chunk metadata (added during M-1.6 for Mastodon and Bluesky; Reddit and HN already used `comment_id`). **Production citations now jump to the specific reply when the chunk originated from one** — Reddit `#comment-<id>` anchor, HN per-item endpoint, Mastodon per-reply status URL, Bluesky per-reply web URL.
- **LLM-prompt update (T-1.5.12.3).** `USED_SOURCES_PROMPT` rewritten — was YouTube-only ("whose video was actually cited"), now refers to "source" generically and lists all 5 source types so the auditor knows the variety. Chunk-listing format changed from `index | video_id | video_title` to `index | [source_type] | source_id | title` with per-source prefixes (`[reddit_post]` / `[hn_story]` / `[mastodon_post]` / `[bluesky_post]` / `[video]`).
- **7 new chunking tests** covering single-reply propagation, video transcript empty defaults, dominant-segment heuristic across straddling replies, sentence-expansion preserving `extra`, defensive handling of malformed `extra` (non-dict / bad-type `depth`), OP-dominates-chunk fallback. **22 existing chunking tests still pass** — tuple-shape change is internal; public input/output contract unchanged for YouTube callers. Backend suite 566 → 573.
- **S-1.5.12 🟡 → 🟢** closes the M-1.5/M-1.6 polish-backlog top item.

### Backend reference enrichment — polymorphic source metadata in chunks (PR #131)

- **Closes the missing backend half of M-1.5 / M-1.6's polymorphic citation pipeline.** Frontend rendering for Reddit / HN / Mastodon / Bluesky citations was renderer-complete since [PR #117](https://github.com/khoks/VideoResearchPro/pull/117) and PRs [#127](https://github.com/khoks/VideoResearchPro/pull/127)–[#129](https://github.com/khoks/VideoResearchPro/pull/129), but `chunk_transcript()` was still writing only YouTube-shaped fields to Chroma — every social-media chunk fell through to the `_chunk_to_reference` video default in production despite the source row carrying the right `source_type`.
- **Threaded per-document polymorphic fields end-to-end.** `_build_video_metadata()` now lifts `source_type` / `source_id` / `source_url` / `permalink` / `author` / `subreddit` / `instance` from the `Document` row + `Document.source_metadata_json` (defensive against `None` and non-dict shapes for older rows). `chunk_transcript()` writes those keys to every chunk's metadata block alongside the legacy YouTube-shaped fields. Legacy chunks already in Chroma keep working — `_chunk_to_reference` falls back to the YouTube branch when `source_type` is missing.
- **Production citations now render polymorphically across all 5 source types** (`video` / `reddit_post` / `hn_story` / `mastodon_post` / `bluesky_post`) with OP-level permalinks.
- **Per-segment fields deferred.** Per [D-030](docs/decisions.md#d-030--backend-reference-enrichment-ships-per-document-polymorphic-chroma-metadata-first-per-segment-comment_idcomment_url-deferred-2026-05-03), reply-anchor `comment_id` / `comment_url` (which would deep-link a citation to the specific reply rather than the OP) wait for a structural change to `chunk_transcript()` to preserve per-segment `extra` through sentence-expansion + greedy-packing. The connector flatten layer already emits them; the chunker strips them at the segment-tuple boundary today.
- **Tests.** 17 new tests — 11 in `test_chunking.py` (polymorphic field propagation per source_type, multi-chunk consistency, legacy default behavior), 6 + 6 in new `test_build_video_metadata.py` (per-source field-lifting from `source_metadata_json`, defensive None / non-dict / missing-source_url). Full backend suite: 549 → 566 (+17 new). Frontend `npm run build` clean (no frontend changes).

### Bluesky connector — closes M-1.6 (S-1.5.7, PR #129)

- **Added `backend/app/sources/bluesky/`** — fourth social-media connector after Reddit / HN / Mastodon. `BlueskyConnector(BaseConnector)` covers `app.bsky.feed.searchPosts` (text discovery), `app.bsky.feed.getPostThread` (full thread tree with depth=6), `app.bsky.actor.getProfile` (handle/DID resolution), and `app.bsky.feed.getAuthorFeed` (creator-feed listing).
- **No-auth public XRPC base.** Per [D-028](docs/decisions.md#d-028--bluesky-uses-public-unauthenticated-at-proto-xrpc-deviation-from-s-157-spec-2026-05-03), Bluesky exposes its public read endpoints at `https://public.api.bsky.app/xrpc/` without app-password auth — the original S-1.5.7 spec called for app-password auth, but it's not needed for ingest of public posts. Configurable via `BLUESKY_XRPC_BASE` so operators running a private PDS or who need higher throughput can swap in an authenticated base.
- **Identity convention.** Per [D-029](docs/decisions.md#d-029--bluesky-source_id-is-the-at-uri-not-the-bskyapp-web-url-2026-05-03), `Candidate.source_id = f"bluesky:{at_uri}"` — AT-URIs are stable across handle renames (DIDs are permanent) so `(source_type, source_id)` dedup holds. The bsky.app web URL goes into `Candidate.source_url` for browser-friendly citations.
- **Reposts excluded** from creator-feeds (entries with `reason.$type === '...#reasonRepost'`) — parity with Mastodon's reblog exclusion.
- **Recursive thread tree** walked depth-first; replies sorted by `likeCount`, trimmed to `BLUESKY_COMMENT_DEPTH_DEFAULT` (default 50). Each reply segment carries its own `comment_url` (the reply's bsky.app web URL) for the future per-segment reply-anchor refinement noted in PR #131. Blocked / not-found posts (`#blockedPost`, `#notFoundPost`) skipped during walk; visible children still render.
- **Language extraction** from `record.langs[0]` flows through to `ExtractedText.language` for multilingual indexing.
- **Frontend wiring.** `bluesky_post` added to `SourceMetadata` discriminated union → `SOURCE_CONFIGS` mapped-type registry refused to compile until matching entry registered (`BlueskyGlyph` SVG + author/likes/replyCount/repostCount chips). `videoToApprovalProps` mapper extension; `<CitationLink>` renderCitation case (`@handle.bsky.social · title`); polymorphic `_chunk_to_reference` branch in qa_agent (with `comment_url` reply-anchor pattern matching Mastodon's).
- **Tests.** 43 new tests in `test_bluesky_connector.py` covering search/list/metadata/text wiring, classifier integration, AT-URI validation, `comment_url` emission per reply, blocked-post / repost skipping, profile-URL parsing for `resolve_creator_id`, depth-marker reconstruction, language extraction, client base-URL + limit clamping. 3 new tests in `test_qa_agent.py` for the polymorphic citation branch. Full backend suite: 506 → 549 (+43 + 3 new).
- **Closes Milestone M-1.6** ✅ — Mastodon (PR #128) + Bluesky shipped same-day. The polymorphic plumbing established in M-1.5 generalises across new source types without core changes; validated three times in this milestone (Mastodon connector, Bluesky connector, then the backend reference enrichment in #131).

### Mastodon connector — M-1.6 first half (S-1.5.6, PR #128)

- **Added `backend/app/sources/mastodon/`** — third social-media connector. `MastodonConnector(BaseConnector)` covers public hashtag-timeline discovery (`/api/v1/timelines/tag/<hashtag>`), per-status fetch via `/api/v1/statuses/<id>` + `/context`, account resolution via `/api/v1/accounts/lookup`, and creator-feed listing via `/api/v1/accounts/<id>/statuses`. No auth required.
- **Topic→hashtag normalisation.** Per [D-027](docs/decisions.md#d-027--mastodon-discovery-uses-the-public-hashtag-timeline-no-auth-single-hashtag-normalisation-2026-05-03), Mastodon disables full-text search by default to honour user privacy, so the public hashtag timeline is the discovery surface. Topic queries are normalised to a single alphanumeric hashtag using Unicode `L*` / `N*` / `M*` categories — `str.isalnum()` would have stripped Devanagari combining marks (`ि`, `्`) and mangled Hindi/Marathi/Bengali queries. `unicodedata.category(ch)[0]` matches what Mastodon's own hashtag parser does.
- **Identity convention.** `Candidate.source_id = f"mastodon:{status_id}"`. The instance is configurable via `MASTODON_INSTANCE_BASE` (default `mastodon.social`); self-hosters can override.
- **Reply tree handling.** Mastodon's `/context` returns descendants flat with `in_reply_to_id` pointers; depth is reconstructed by walking the parent chain. Replies sorted by `favourites_count`, trimmed to `MASTODON_COMMENT_DEPTH_DEFAULT` (default 50). Each reply segment carries `comment_id` + (placeholder for `comment_url` once chunker rework lands) for the future reply-anchor pattern.
- **Fail-soft on context fetch.** If `/context` errors (instance overloaded, partial outage), the connector degrades to OP-only segments rather than failing the whole status. Same pattern Reddit and HN use for partial-failure tolerance.
- **HTML scrub.** Mastodon delivers `content` as HTML; cheap regex-based tag strip (parity with HN's flatten — full HTML parser deferred until quality requires it).
- **Status `language` flow-through.** `status.language` lands on `ExtractedText.language` so multilingual indexing knows what it's storing.
- **Frontend wiring.** `mastodon_post` in `SourceMetadata` discriminated union; `MastodonGlyph` SVG; chip layout (author / instance / favourites / replyCount); `videoToApprovalProps` splits `acct = user@instance` defensively when `instance` field isn't supplied separately; `<CitationLink>` renderCitation case (`@user@instance · title`); polymorphic `_chunk_to_reference` branch with `comment_url` reply-anchor pattern (when chunking eventually emits it).
- **Tests.** 48 new tests in `test_mastodon_connector.py` covering hashtag normalisation (incl. Devanagari combining marks), search/list/metadata/text wiring, classifier integration, OP-only fallback when `/context` fails, depth-marker rendering, HTML strip, registry registration. 3 new tests in `test_qa_agent.py`. Full backend suite: 503 → 506 base (+48 + 3 new).

### docs: feature-roadmap M-1.6 closure entry (PR #130)

- **Aligned `docs/feature-roadmap.md` with `docs/initiatives.md`** so both narrative docs reflect M-1.6 ✅. The doc was still listing M-1.6 under "next milestones" while initiatives.md had already been flipped during the Bluesky PR merge. Pure doc-currency fix.

### L1 multi-source ingest — HN connector (S-1.5.2)

- **Added `backend/app/sources/hn/`** — second non-video L1 connector. `HNConnector(BaseConnector)` covers Algolia HN search (`/search?tags=story`), `list_creator_items` via `/search_by_date?tags=story,author_<name>`, and full thread fetch via `/items/<id>`. HN's Algolia API is **unauthenticated** so the client is markedly simpler than Reddit's — no OAuth, no token cache, no 401-retry. Singleton client + `_reset_for_tests()` follow the same shape as `reddit/client.py`.
- **Comment-tree flatten** mirrors Reddit's segment shape so chunking + embedding stay unchanged across both source types: OP first (title + HTML-scrubbed body), then top-N comments by `points` (HN's `score` equivalent) with `↳` Unicode depth markers per nesting level. HN comment bodies are HTML-rendered (`<p>` tags + entities), so the flatten module includes a cheap scrub before joining.
- **Identity convention.** `Candidate.source_id = f"hn:{story_id}"` — namespaced to avoid collisions with YouTube's 11-char IDs and Reddit's base36 IDs while the `documents.video_id` PK column is shared across source types. Connector tolerates both prefixed and unprefixed IDs at the `fetch_metadata` / `fetch_text` boundary.
- **Shared text-utils module.** `_WORDS_PER_SECOND = 3.0` and `_segment_for_text(...)` extracted from `app/sources/reddit/flatten.py` into `app/sources/_text_utils.py` so future text-based connectors (article, forum_post, pdf) share **one** tunable per [D-013](docs/decisions.md) instead of redeclaring the constant per package. Reddit's flatten now imports the helper.
- **Eager registration** in `app/sources/__init__.py` so `connector_for("hn_story")` resolves out of the box.
- **Tests.** 31 unit tests in `backend/tests/test_sources/test_hn_connector.py` mirroring the Reddit suite (search 5 / list_creator_items 3 / fetch_metadata 5 / fetch_text 3 / flatten 9 / identity 2 / client 4). Reddit's 29 tests stay green after the `_text_utils` extraction. Full backend suite passes 388 (excluding 5 pre-existing `test_llm_routing*` failures unrelated to this branch).
- **Env vars** added: `HN_USER_AGENT` (Algolia is generous but a polite UA string keeps us out of any heuristic rate-limiter), `HN_RATE_LIMIT_RPM` (default 60 — well under any soft cap), `HN_COMMENT_DEPTH_DEFAULT` (default 50, parity with Reddit).
- *(T-1.5.2.2 — date-range filter via `numericFilters=created_at_i>...,<...` — implicitly out of scope. Algolia exposes the filter, but the topic-job submit form has no date-range input yet, so wiring it on the connector side without a UI surface would be dead code. Will land alongside the date-range form field.)*

### Pseudo-timestamps codified at 3 wps for text-based connectors (D-013)

- **Captured the Reddit-introduced convention as ADR D-013** in [docs/decisions.md](docs/decisions.md). Text-based connectors (Reddit / HN / future article / forum / PDF) synthesise per-segment `start` + `duration` at **3 words/second** so the chunker — designed around video transcripts — sees monotonic non-negative timestamps and packs text into chunks identically across source types. Documents the alternatives considered (true-zero timestamps, per-source rates, parameterising the chunker) and why a single shared constant won.
- **Pointer added** in [docs/source-types.md](docs/source-types.md) so future connectors copy the same constant rather than picking a fresh number.
- *(Doc-only — the constant itself was already added in PR [#70](https://github.com/khoks/VideoResearchPro/pull/70). PR [#72](https://github.com/khoks/VideoResearchPro/pull/72) just records the why so the next connector author doesn't relitigate the choice.)*

### L1 multi-source ingest — Reddit connector (S-1.5.1)

- **Added `backend/app/sources/reddit/`** — first non-video L1 connector. `RedditConnector(BaseConnector)` covers `/search.json`, per-sub `/r/<sub>/search.json`, `/user/<name>/submitted.json`, `/api/info.json`, and `/comments/<id>.json` for full thread fetch.
- **Script-app OAuth** (`client_credentials` flow) with token caching, 401-driven refresh, and a token-bucket rate limiter pinned to `REDDIT_RATE_LIMIT_RPM` (default 100 rpm → ~0.6s spacing — Reddit's free OAuth tier).
- **Comment-tree flatten** (`flatten.py`) — OP first (title + selftext joined), then top-N comments by score with `↳` Unicode depth markers per nesting level. Emits chunkable `{text, start, duration, extra}` segments with synthesised pseudo-timestamps at 3 wps so the existing transcript chunker contract holds without a special-case branch. `kind=="more"` placeholders are skipped (expanding them is deferred).
- **Identity convention.** `Candidate.source_id = f"reddit:{post_id}"` — namespaced to avoid collisions with YouTube's 11-char IDs (and HN's integer IDs) inside the shared `documents.video_id` PK column. The connector also accepts both prefixed and unprefixed IDs at the `fetch_metadata` / `fetch_text` boundary so callers don't have to know.
- **Eager registration** in `app/sources/__init__.py` — importing the package registers the connector so `connector_for("reddit_post")` resolves out of the box.
- **Tests.** 29 unit tests in `backend/tests/test_sources/test_reddit_connector.py` covering connector / flatten / client (token caching, 401-retry, missing-credential guard). The whole `tests/test_sources/` suite stays green at 54/54; full backend suite passes 357 (excluding 5 pre-existing LLM-routing failures unrelated to this branch).
- **Env vars** added: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`, `REDDIT_RATE_LIMIT_RPM`, `REDDIT_COMMENT_DEPTH_DEFAULT`. Documented in [.env.example](.env.example) and [CLAUDE.md](CLAUDE.md).
- *(Storage wiring (T-1.5.1.4 — landing rows in `documents` with `source_type='reddit_post'`), end-to-end pipeline test (second half of T-1.5.1.6), Reddit approval-UI card variant (T-1.5.1.7), and `reddit_post`-aware citation rendering (S-1.5.5) are deferred to follow-up PRs that wire Reddit through the job orchestrator. The connector contract is the foundation; the orchestrator integration is the next layer.)*

### L1 multi-source ingest — PR 4: rename `videos` table → `documents`

- **Pure rename migration** at `backend/alembic/versions/01c5b6dae736_rename_videos_to_documents.py` (revises `f6a7b8c9d0e1`). Renames the table, drops/recreates the two existing indexes (`ix_videos_channel_id` and `ix_videos_source_type_source_id` → `ix_documents_*`), and re-points the `job_videos.video_id` foreign key from `videos.video_id` to `documents.video_id` on non-SQLite via `batch_alter_table`. Reversible.
- **Renamed `app/models/video.py` → `app/models/document.py`** with `class Video` → `class Document`, `__tablename__ = "documents"`, and the legacy `__init__` compat shim preserved (defaults `source_type='video'`, `source_id` from `video_id`, `source_url` from `url`). The PK column is intentionally still `video_id` — promoting it to a UUID `id` would cascade to `job_videos.video_id` and `transcript_cache.video_id` foreign keys and is deferred to a later PR.
- **Propagated `Video` → `Document` across 14 importers** under `app/routers/`, `app/services/`, `app/tasks/`, `app/agents/` plus `app/models/__init__.py`, `app/models/job.py` (relationship), and `app/models/job_video.py` (FK target). User-facing strings (404 messages, LLM prompt formatting, Celery progress messages like `f"Video {attempted}/{total}:"`) intentionally left unchanged — they refer to the user-facing concept of a YouTube video, not the ORM class.
- **Tests** — every `from app.models.video import Video` import migrated to `from app.models.document import Document`; `db.query(Video)`, `db.get(Video, ...)`, and `Video(...)` constructor calls in 8 test files updated to `Document`. 320/320 backend tests pass excluding 5 pre-existing LLM-routing failures unrelated to this PR.
- *(After PR 4, the schema, model class, and every Python call site speak `Document`. Connectors (PR 2/3) and the orchestrator are now ready for the next L1 step: a non-video connector — article or PDF — without further table renames.)*

### L1 multi-source ingest — PR 3: route remaining YouTube call sites through the connector

- **`app/tasks/job_tasks.py` migrated** — channel-job and subscription-job orchestrator paths now resolve creators, list creator items, fetch metadata, and fetch creator profiles via `connector_for("video")` rather than calling `youtube_service` directly. The single exception is `youtube_service.get_channel_videos_all(...)` in the subscription uploads-walk: it depends on the cached `uploads_playlist_id` optimization (saves one `channels.list` quota unit per channel) and the connector contract has no per-source-type optimization slot today. Documented inline; future PR can extend `list_creator_items` with an `extra` kwargs bag.
- **`app/agents/search_agent.py` migrated** — broad-query search, preferred-channel uploads-walk, and the missing-metadata enrichment step all route through the connector. `youtube_service.get_channel_subscribers(...)` (a multi-channel batch helper with no connector equivalent) stays direct.
- **Boundary adapters** — both modules add a small private `_source_metadata_to_legacy_dict(...)` (and, in `search_agent.py`, `_candidate_to_legacy_dict(...)`) that flatten the typed connector dataclasses back to the dict shape the existing downstream code expects (`_upsert_video_and_link`, the duration filter, the LLM rank prompt). Keeps PR 3 minimal — a future PR can promote callers to consume `Candidate` / `SourceMetadata` directly when `videos` → `documents` lands.
- **`BaseConnector.resolve_creator_id(hint, *, job_id="")` added** — optional method that resolves a free-text creator hint (URL, handle, name, raw ID) to the canonical `creator_external_id`. YouTube implementation forwards to `youtube_service.resolve_channel_id`. Default returns None for source types without a creator concept (PDF).
- **`job_id` propagation** — `BaseConnector.list_creator_items`, `fetch_metadata`, and the new `resolve_creator_id` / extended `fetch_creator` now accept `*, job_id: str = ""` so connectors can forward correlation IDs into provider-side log lines (every YouTube call already logs `[job:...]`).
- **Tests** — added `test_resolve_creator_id_forwards_to_service` and `test_resolve_creator_id_returns_none_when_service_returns_none` to `tests/test_sources/test_youtube_connector.py`. Existing `tests/test_agents/test_search_agent.py` side-effects extended to accept the connector's `job_id=""` kwarg (single-line `**_` change). 333/333 backend tests pass excluding 5 pre-existing LLM-routing failures unrelated to this PR.
- *(After PR 3, every YouTube call in production code that has a connector equivalent now goes through `BaseConnector`. This is the precondition for PR 4 — `videos` → `documents` rename — which can finally rename the table without rewriting orchestrator call sites again.)*

### L1 multi-source ingest — PR 2: connector abstraction

- **Introduced the `BaseConnector` abstract base class** (`backend/app/sources/base.py`) and four typed dataclasses (`Candidate`, `ExtractedText`, `SourceMetadata`, `CreatorMetadata`) in `backend/app/sources/types.py` — the shape every future source-type connector (podcast, article, tweet, forum_post, pdf) plugs into. See [docs/source-types.md](docs/source-types.md) §"connector contract".
- **Added a process-global registry** at `backend/app/sources/registry.py` mapping `source_type → connector instance`. Connectors register themselves at import time; the orchestrator resolves them via `connector_for(source_type)`. Re-registering the same type overrides the prior entry — useful for swapping fakes in tests.
- **Refactored today's YouTube ingest** into the first concrete connector at `backend/app/sources/video/connector.py`. Pure pass-through wrapping of `app.services.youtube_service` — every YouTube quirk (API quota, transcript-API retry/back-off, Whisper fallback, yt-dlp audio download, subscriber enrichment) stays in `youtube_service`; the connector only reshapes provider dicts into typed dataclasses.
- **Switched the `fetch_transcript` seam in [backend/app/tasks/job_tasks.py](backend/app/tasks/job_tasks.py)** to route through `connector_for(video.source_type).fetch_text(...)`. Behavior-preserving: existing topic / channel / subscription jobs run identically — but the abstraction is now exercised in production code, proving it works end-to-end before any non-video connector ships.
- **Tests:** `backend/tests/test_sources/test_registry.py` (7 tests) locks the registry contract and verifies the YouTube connector implements every `BaseConnector` hook. `backend/tests/test_sources/test_youtube_connector.py` (14 tests) mocks `youtube_service` and asserts each connector method produces correctly-shaped Candidate / SourceMetadata / ExtractedText / CreatorMetadata objects, including edge cases (sparse search dicts, missing optional fields, no-text segments). `tests/test_tasks/test_subscription_task.py` updated to also patch the connector's `youtube_service` binding now that the call site goes through the connector.
- *(Other call sites — `youtube_service.search_videos`, `get_video_details`, `get_channel_metadata`, `get_channel_videos*` — are still invoked directly from `job_tasks.py` / `search_agent.py` / `channels.py`. They migrate to `connector.search()` / `fetch_metadata()` / `fetch_creator()` / `list_creator_items()` in PR 3.)*

### L1 multi-source ingest — PR 1: additive schema

- **Added the source-type discriminator and supporting columns** to `videos` and `channels` so the existing tables can host non-video sources (podcasts, articles, threads, PDFs, …) in subsequent PRs without another migration. Pure additive: no renames, no behavior change. See [docs/source-types.md](docs/source-types.md).
- **`videos`** gains `source_type` (default `'video'`), `source_id` (NOT NULL, backfilled from `video_id`), `source_url`, `source_metadata_json`, `language`, `word_count`, `user_provenance_json`. `duration_seconds` is now nullable (articles and threads have no duration). New unique index `ix_videos_source_type_source_id` for cross-source dedup scoped by source-type.
- **`channels`** gains `source_type`, `creator_external_id` (NOT NULL, backfilled from `channel_id`), `source_weight` (default `1.0` — feeds the L4 retrieval re-ranking), and `creator_metadata_json`.
- **Backfill** runs in the same migration and sets every existing row to `source_type='video'`, `source_id=video_id`, `creator_external_id=channel_id`. 912/912 videos and 48/48 channels migrated cleanly on the local DB.
- **Model `__init__` overrides** keep the legacy YouTube ingest call sites working untouched: passing only `video_id`/`url`/`channel_id` auto-populates the new columns. New tests in `tests/test_models/test_multi_source_columns.py` lock in the defaults, the unique constraint, and cross-source-type independence.
- **Migration:** `b8c9d0e1f2a3_multi_source_columns.py` (revises `a7b8c9d0e1f2`). Reversible — `alembic downgrade -1` restores the prior schema cleanly.
- *(Channel→Creator and Video→Document table renames are deferred to a later PR.)*

### Branding & documentation refresh

- **Rebrand to Pratidhvani (प्रतिध्वनि).** Sanskrit for "echo" — captures both the *sources echoing into the library* and *past exchanges echoing into future ones*. Legacy `VideoResearchPro` name retained only in grandfathered env-var names like `CHROMA_GLOBAL_COLLECTION_NAME=videoresearchpro_global` for back-compat. See [docs/branding.md](docs/branding.md).
- **Warm-editorial visual language.** Retired the `#667eea → #764ba2` purple-blue gradient. New palette: paper-tone backgrounds, oxblood / forest-teal / vintage-gold accents, Fraunces + Source Serif Pro + Inter + JetBrains Mono typography. See [docs/ui-design.md](docs/ui-design.md).
- **Full docs refresh.** Split stale monoliths into canonical single-topic docs with an explicit ownership matrix:
  - New: [docs/vision.md](docs/vision.md), [docs/branding.md](docs/branding.md), [docs/feature-roadmap.md](docs/feature-roadmap.md), [docs/saas-roadmap.md](docs/saas-roadmap.md), [docs/personal-brain.md](docs/personal-brain.md), [docs/source-types.md](docs/source-types.md), [docs/api-reference.md](docs/api-reference.md), [docs/ui-pages.md](docs/ui-pages.md), [docs/contributing.md](docs/contributing.md), [docs/testing.md](docs/testing.md), [CHANGELOG.md](CHANGELOG.md) (this file).
  - Refreshed: [docs/architecture.md](docs/architecture.md), [docs/requirements.md](docs/requirements.md), [docs/ui-design.md](docs/ui-design.md).

*(No code changes shipped in this pass — documentation and identity only.)*

### Echo — Ring 3 vision capture (docs only, 2026-04-24)

- **Named the L3 user-facing surface "Echo"** — a proper-noun reuse of the brand's literal meaning (*Pratidhvani* = echo). Echo is the always-evokable "Jarvis-style" floating bubble that speaks *as the user themselves*: synthesising sources, history, personal facts, activity, and personality signals into responses that mirror the user's lens, methodology, and conclusions. See [docs/personal-brain.md](docs/personal-brain.md) §"Echo — the named L3 surface".
- **Added Domain 5 — constant-stream intake (push-mode sharing).** OS share targets, browser extension, email-in inbox, drag-drop, manual quick-share — friction-free intake of liked videos / reels / memes / WhatsApp threads / Keep notes / quotes / voice memos. New `shares_inbox` table and `shares_global` Chroma collection. Cross-feeds Domains 1 (facts), 2 (events), 3 (personality signals), and the source library. The single richest signal feeder for Echo readiness.
- **Reframed Domain 3 from "voice capture" to "personality capture".** Style/cadence is one signal among many; the new schema treats `trusted_conclusion`, `preferred_solution`, `recommendation_lens`, `apprehension`, `methodology`, `topic_emphasis`, `perception_lens` as first-class signal types alongside the existing style layer.
- **Two complementary personality-capture modes documented:** **Mode A** prompt-time retrieval of personality signals (default, ships first); **Mode B** opt-in per-user fine-tuning on curated dataset themes (problem-solution, recommendation lens, situational priority, opinion-formation, methodology) once readiness is crossed.
- **Cold-start readiness gating.** Echo refuses to mimic poorly: until thresholds are crossed across all five domains, the bubble is dimmed and shows a progress meter. Better to refuse than to break trust.
- **Captured the user's verbatim 2026-04-24 vision brain-dump** in [docs/notes/2026-04-24-echo-feature-vision.md](docs/notes/2026-04-24-echo-feature-vision.md) as a raw safekeeping artifact. The structured docs (personal-brain.md, feature-roadmap.md, vision.md) are the synthesis; the notes file is the source of truth if synthesis ever drifts from intent.
- **Updated:** [docs/personal-brain.md](docs/personal-brain.md), [docs/feature-roadmap.md](docs/feature-roadmap.md) (L3 entry renamed and expanded to five components), [docs/vision.md](docs/vision.md) (Ring 3 + Phase 6 milestone reference Echo by name).

*(Still docs-only — no code or schema changes. The L3 build-out is targeted Phase 6 / 2027 Q3+.)*

---

## Recently shipped

### Per-use-case LLM config + smoke-check + fail-soft UI · [#62](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/62)

- Every LLM call site in the codebase is now a named **use case** with a default `(provider, model, reasoning)` triple in `app/services/llm_routing.py::USE_CASE_REGISTRY`. Nineteen entries cover Q&A (job-scoped, library-scoped, history-chat), knowledge extraction, topic search, and report generation.
- New `LLM_USE_CASE_CONFIG` env var overrides any entry without editing code: `use_case=provider:model[:reasoning]`, comma-separated. Typos are warnings, never fatal.
- Providers supported: `openai`, `anthropic`, `google`, `local` (any OpenAI-compatible endpoint — LM Studio, Ollama, vLLM, llama.cpp-server).
- Reasoning normalized across providers (`off` / `minimal` / `low` / `medium` / `high` / `auto`), mapped to each SDK's native parameter.
- **Startup smoke check.** `run_startup_probes` fires a one-token probe per unique `(provider, model)` pair at boot; results land on a process-global `LLMStatus` singleton exposed via `GET /api/v1/health` and `GET /api/v1/health/llm`.
- **Fail-soft.** When a probe fails the app stays up; a frontend banner lists affected features and pages disable their primary action (Ask question, Generate report, Extract knowledge) while everything else stays interactive.

### Video-knowledge migration, Q&A history retrieval, LLM routing registry · [#47](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/47)

- Consolidated the formerly scattered LLM-provider selection logic into `llm_routing.py` as the single source of truth.
- Fixed Q&A History retrieval to pull from the central `qa_library_global` collection rather than per-job scopes.
- Merged the knowledge-report migration into the main Alembic chain so fresh installs don't need manual Unit-4 steps.

### Exports — drop Unit 2/4 fallback guards · [#46](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/46)

- Removed "does this column exist yet?" defensive guards from the exports service now that the `qa_library_global` and `video_knowledge` models have shipped.

### Dataset exports for fine-tuning · [#38](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/38) · [#42](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/42)

- Four streaming JSONL endpoints that dump your accumulated Q&A and knowledge artifacts as training-ready datasets:
  - `GET /api/v1/exports/qa-dataset/openai.jsonl` — OpenAI chat format
  - `GET /api/v1/exports/qa-dataset/tuple.jsonl` — plain `{system, user, assistant}` tuples
  - `GET /api/v1/exports/knowledge-dataset/openai.jsonl` — knowledge reports, chat format
  - `GET /api/v1/exports/knowledge-dataset/tuple.jsonl` — knowledge reports, tuple format
- Endpoints stream via `StreamingResponse` with SQL iterators so memory stays constant for arbitrarily large datasets.
- Q&A dataset unions `qa_exchanges` + `library_qa_exchanges` + `qa_history_exchanges` ordered by `created_at`.
- System prompts are baked into `services/dataset_service.py` as module constants.
- New Exports page in the frontend offers one-click downloads with row counts.

### Video knowledge artifacts (Unit 4 + Unit 5) · [#43](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/43) · [#40](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/40)

- Every `videos` row now carries three nullable columns — `extracted_knowledge_json`, `knowledge_report_md`, `knowledge_extracted_at`.
- New **Generate knowledge report** button on each video row triggers a map-reduce LangGraph agent (`knowledge_agent.py`) that splits the transcript into token-budgeted batches, extracts structured `{topics, concepts, events, facts}` per batch, merges with dedupe, and synthesizes a Wikipedia-paragraph-style Markdown document.
- New `POST /api/v1/videos/{id}/extract-knowledge` + `GET /api/v1/videos/{id}/knowledge` endpoints. 409 if already extracted unless `?force=true`.
- Frontend presents the artifact in a slide-in drawer.

### Q&A History chat (Unit 2 + Unit 3) · [#45](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/45) · [#39](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/39) · [#44](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/44)

- New central ChromaDB collection (`qa_library_global`) indexes every Q&A exchange — job-scoped, library-scoped, and history-chat — as single documents (question + answer concatenated, not chunked).
- Upserts run post-commit on a best-effort basis; Chroma failures never break the Q&A response.
- Worker-startup backfill idempotently upserts every existing row from `qa_exchanges`, `library_qa_exchanges`, and `qa_history_exchanges`.
- New `/qa-history` page lets you ask meta-questions across all past Q&A ("summarize everything I've learned about tariffs") with citations linking back to the source exchange.
- Powered by `qa_history_agent.py`: `retrieve_past_exchanges → refine_context → synthesize_answer`.

### Duplicate / re-run any job · [#38](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/38) (partial) and prior

- **Duplicate / Re-run** button on both the Jobs list and each Job Detail page navigates to the submit form with every parameter pre-filled from the original job.
- New **Job Parameters** card on the detail page surfaces the full submission payload in read-only form so you can see months later exactly what was asked for.
- Zero-backend-change feature — the frontend round-trips the existing `Job` response back into the form.

### Reliability & observability

- **Orphan-state backstop.** Every orchestrator task now runs a `finally`-clause safety net that fails any job stuck in a transient status (`pending` / `searching` / `extracting` / `building_rag` / `generating_report`) when the task returns, so a silent bug can't strand the UI at 5% forever.
- **Worker log capture.** `restart_services.ps1` now redirects every detached runtime's stdout and stderr to per-service `.out.log` / `.err.log` files at the repo root (uvicorn, Celery, Vite frontend).
- **Whisper retry.** Transient OpenAI errors now retry with backoff; a YouTube IP-block short-circuits the fallback chain so a single bad host doesn't poison an entire batch.
- **Extraction progress persistence.** The attempted-vs-fetched count is now written to the DB every iteration so the frontend progress bar reflects reality even mid-task.
- **Same-batch dedupe.** Prevents duplicate `Channel` / `Video` / `JobVideo` inserts within a single batch.

### Preferred channels on topic jobs · [`c48c7fb`](https://github.com/RahulSinghKhokhar/VideoSearchDB/commit/c48c7fb)

- Search Agent now takes a `preferred_channels` list alongside the topic and instructions. The LLM produces a structured plan (`broad_queries` + `channel_keywords`); preferred channels are resolved to IDs and their uploads playlists are walked directly, then keyword-filtered.
- No more creator names getting stuffed into raw YouTube query strings.

### One-click restart · [`c48c7fb`](https://github.com/RahulSinghKhokhar/VideoSearchDB/commit/c48c7fb)

- `scripts/restart_services.ps1` kills and relaunches all four runtimes (Redis, backend, Celery worker, frontend dev server) in one shot on Windows.
- `POST /api/v1/admin/restart` drives the same script from inside the running backend via a detached trampoline process. Returns `202 Accepted` immediately.
- Useful query params: `?skip_frontend=true`, `?delay=5`.

### Global video library · prior

- `videos` is now a shared, global, deduplicated table — one row per YouTube `video_id` ever.
- `channels` stores subscribed channels with `last_synced_at` for incremental re-sync.
- `job_videos` many-to-many join links jobs to videos.
- Deleting a job drops its `job_videos` rows but leaves the videos and chunks in the library so other jobs can still reference them.
- Single global ChromaDB collection `videoresearchpro_global`; per-job scoping is a metadata filter at query time.

### Channel subscriptions · prior

- New subscription job type: fire-and-forget ingestion of every video on a channel's uploads playlist — no approval step, no report. Subsequent jobs that reference the same videos skip re-fetch / re-transcribe / re-embed entirely.

### Library-wide Q&A · prior

- `POST /api/v1/library/qa` and the **/library/qa** page let you ask questions across every transcribed video in the library, not just one job.
- Citations link back to the source video with `&t=` timestamps.

### Multilingual transcription & answers · prior

- Whisper called with `task="transcribe"` (not `translate`) to preserve the speaker's language(s). Mixed-language audio (e.g., Hindi-English code-mixed) is transcribed faithfully.
- Embeddings use the multilingual `paraphrase-multilingual-MiniLM-L12-v2` so a Hindi transcript and an English question land in similar vector space.
- Q&A agent accepts an `answer_language` parameter (default English) and translates quoted non-English context into English (preserving proper nouns) while responding in the requested language.

### Authentication · prior

- Email + password JWT auth with user-scoped jobs, Q&A history, and knowledge artifacts. Channels and videos remain global (shared library), but every mutating endpoint is scoped to `current_user`.
