# M11 — Public report sharing: plan

**Board:** [E-8.11](../initiatives.md#e-811--public-report-sharing-m11) · **Roadmap:** [M11](../feature-roadmap.md#m11--public-report-sharing-) · **Research date:** 2026-10-19 · **Status:** design complete, **not accepted**: whether this ships before billing and takedown tooling is the user's call (open question 1).

## Problem

A report is the most shareable thing the app makes and there is no way to show it to anyone without an account. The roadmap sketched a signed URL per report, read-only, expiring, "paving the way for SaaS sharing". The tier gate `public_report_sharing` exists with nothing behind it. The vision's principle is explicit: sharing is signed-URL, explicit and revocable; cross-user library sharing stays deferred.

## Verified current state (2026-10-18)

- No `report_shares` table or public route; every report route requires auth (header or the `?token=` JWT fallback used by the iframe).
- Rate limiting is per user tier and per IP for unauthenticated GETs (E-5.5); there is no per-share quota and no abuse-report pipeline; content policy and takedown workflow are T-5.5.6, gated on this feature.
- `audit_log` exists; `email_service` exists.
- JWTs are minted and verified with `python-jose` 3.5.0, whose latest release carries CVE-2026-85394 (CVSS 9.3, published 2026-09-03, unfixed: a DER public key accepted as an HMAC secret). The three decode sites pin `algorithms=[HS256]`, which neutralises the known path, but the dependency is effectively unmaintained. Tracked as [T-5.4.9](../initiatives.md#e-54--auth-hardening). **Share tokens must not be JWTs.**
- Reports quote transcripts; a public share makes YouTube-derived text public.

## Chosen approach

- **Tokens**: opaque `secrets.token_urlsafe(32)` (256 bits; OWASP's floor for a capability is 64) stored as SHA-256 in `report_shares(id, tenant_id, job_id, token_hash, expires_at, revoked_at, view_count, created_at)`; looked up by hash; token in the **path** (`/s/<token>`), never a query string (query strings end up in logs and analytics). Revocable per link, expiring, auditable, standard library only. `itsdangerous` (BSD-3-Clause) would give expiry but not per-link revocation.
- **Defaults**: off per report; default expiry 30 days with an explicit "no expiry" choice; a per-tenant cap on active shares; `SHARING_ENABLED` environment kill switch; no "discoverable" toggle, ever (the ChatGPT incident of 2025-07-31, about 4,500 shared chats indexed by Google through an opt-in checkbox, which OpenAI removed the same day). The pattern that Notion, Google Drive, NotebookLM and Claude artifacts converge on: off by default, one toggle, a visible "public" badge, revoke kills the link immediately.
- **Headers on the public route**: `X-Robots-Tag: noindex, nofollow` and `<meta name="robots" content="noindex">` (and the path must stay crawlable, not blocked in `robots.txt`, or the noindex is never seen); `Referrer-Policy: no-referrer`; `Cache-Control: private, no-store` so revocation is immediate through any proxy; per-IP rate limit from E-5.5.
- **Isolation of LLM-written HTML**: the public React route (`/s/:token`) fetches `{title, html, statistics}` and renders through the M8 reader with chrome stripped (no Q&A, no links into the app), so sharing inherits the reading view; a raw-HTML variant, if offered, is served under `Content-Security-Policy: sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src https: data:` as a **header** (`sandbox` is ignored in `<meta>`). Google's guidance for user-hosted content is a separate origin; for SaaS, `share.<domain>` is the recommendation (one DNS record and CORS).
- **Owner UI**: "Share" on the reader and job page; a manage list with view counts and revoke; "Report this page" link on the public page.
- **Takedown hooks**: `audit_log` events `share_created`, `share_revoked`, `takedown`; an operator endpoint to revoke by token hash and mark the report restricted; a `/legal` page with a contact. US safe harbour (17 U.S.C. §512(c)) needs a designated agent registered with the Copyright Office, expeditious removal and a repeat-infringer policy with a 10–14 business-day counter-notice window; India's IT Rules as amended 2025-10-22 (effective 2025-11-15) give 36 hours from a court order or a Joint-Secretary-level notice. These are the T-5.5.6 obligations this feature triggers.

## Alternatives rejected

| Option | Why not |
|---|---|
| JWT share tokens on `python-jose` | Unfixed critical CVE; stateless tokens cannot be revoked per link anyway. |
| `itsdangerous` timed serialiser | No per-link revocation without a denylist. |
| Reusing the iframe's `?token=` pattern | A session JWT in a public URL. |
| A "discoverable on the web" option | The incident above; no business reason. |
| Rendering the raw HTML on the app origin without a sandboxing CSP | Lets LLM-written content run with the app's origin. |

## Schema deltas

`report_shares` as above, `INDEX(token_hash)`, `INDEX(tenant_id, job_id)`; `TIER_CAPABILITIES["active_shares_cap"]`.

## API deltas

```
POST     /api/v1/jobs/{id}/share            {expires_in_days | null}   → {url, expires_at}
GET      /api/v1/jobs/{id}/shares
DELETE   /api/v1/shares/{id}
GET      /s/{token}                         public JSON body for the reader (no auth)
GET      /s/{token}/raw                     optional, CSP-sandboxed HTML
POST     /api/v1/admin/shares/revoke        {token_hash | job_id, reason}  (operator)
```

Settings: `SHARING_ENABLED`, `SHARE_DEFAULT_EXPIRY_DAYS`, `SHARE_PUBLIC_ORIGIN`.

## Modules touched

`models/report_share.py`, one Alembic revision, `services/share_service.py` (new), `routers/shares.py` (new; public and owner routes), `routers/admin.py`, `middleware/rate_limit.py` (public route class), `services/tier_service.py` (cap), `frontend/src/pages/PublicReportPage.tsx` (new, chrome-less reader), `components/reader/ReaderShell.tsx` (M8), `JobDetailPage.tsx`, `routes/index.tsx` (public route outside `ProtectedRoute`), `docs/saas-roadmap.md` §5 (content policy, already anticipates this).

## Risks

- **Public hosting of LLM-written content on the app's domain**: brand, legal and SEO exposure even when sanitised and `noindex`ed.
- **Copyright**: reports quote transcripts; a product decision on quote length, an attribution block and the takedown contact is needed before launch.
- **Token enumeration** is impossible at 256 bits; scraping of known links is not, hence rate limiting and view counts.
- **Abuse pipeline does not exist**: no report-this flow, no fraud signals (T-5.5.7), no content policy (T-5.5.6).

## Test strategy

- Service: token entropy and hashing, expiry, revocation, cap, kill switch.
- Router: public route returns the body without auth; 404 after revocation or expiry (indistinguishable from never-existed); headers present; no job metadata beyond the report; rate limit applies; owner routes isolated by tenant; admin revoke writes the audit event.
- Frontend: the public page has no authenticated calls and no app links (a network assertion in Playwright); the share dialog defaults off with a 30-day expiry.

## First PR (S-8.11.1, if accepted)

Table, service, owner and public routes, headers, kill switch, cap, tests, and the chrome-less reader page. The share dialog and manage list follow.

## Open questions (the user's call)

1. **Launch before billing and abuse prevention?** For: reads are cheap, it is the single highest-leverage growth surface, self-hosters want it regardless, the reader already exists. Against: a public unauthenticated route on the app's domain hosting arbitrary LLM-written content, copyright exposure made public, no abuse signals, no takedown process, free tier plus public hosting invites spam. Cheap mitigations if early: opt-in per report, default off, default expiry, per-tenant cap, `noindex`, per-IP limit, kill switch, "report this page", revoke-all on account lock.
   **Answered 2026-10-25** by [D-112](../decisions.md#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25): no; public sharing (E-8.11) is deferred. The static site zip covers sharing meanwhile (S-6.2.1 accepts `job:<id>`). If sharing is ever built, the takedown and revoke hooks go inside S-8.11.2.
2. **Separate origin for shares** (`share.<domain>`) from the start, or only at SaaS launch?
3. **Quote limits** in public reports: cap quoted transcript length, or publish as is with attribution?

## Sources (fetched 2026-10-19)

Python `secrets` docs; OWASP Session Management cheat sheet; `itsdangerous` PyPI and docs; `python-jose` PyPI and advisories GHSA-3qf3-8w2g-rqmx, GHSA-6c5p-j8vq-pqhj, GHSA-cjwg-qfpm-7377; PyJWT PyPI; Google robots meta tag docs; MDN `Referrer-Policy` and CSP `sandbox`; Google Security Blog on hosting user data (2023); web.dev sandboxed iframes; Search Engine Journal, Search Engine Land and PC Gamer on the ChatGPT shared-chat indexing (2025-07-31); NotebookLM, Notion, Google Drive, Claude artifacts and Perplexity Pages sharing help pages; Cornell LII 17 U.S.C. §512; Copyright Office DMCA agent directory; MediaNama and FPF on India's 2025 IT Rules amendment. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
