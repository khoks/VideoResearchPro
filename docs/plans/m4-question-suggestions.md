# M4 — Question suggestions: plan

**Board:** [E-8.4](../initiatives.md#e-84--question-suggestions-m4) · **Roadmap:** [M4](../feature-roadmap.md#m4--question-suggestions-) · **Research date:** 2026-10-19 · **Status:** recommendation.

## Problem

Every Q&A exchange the user has ever had is embedded in `qa_library_global`, yet nothing uses that corpus to help them ask the next question. The user asked for the app to "learn from past questions". Suggestions are also the first concrete piece of Echo's *anticipation* capability (the vision's "surfaces the questions they would ask next").

## Verified current state (2026-10-18)

- `qa_library_global` holds every exchange (job, library, history) as one document each, with `tenant_id`, `source`, `exchange_id`, `job_id`, `created_at_iso` metadata; `chroma_service.query_qa_collection(query_text, top_k, where, tenant_id)` is the tenant-filtered reader (`T-5.6.6`).
- Per-document knowledge artifacts (`extracted_knowledge_json`: topics, concepts, events, facts) exist where extraction has run; job reports exist as HTML; `compute_statistics` yields corpus statistics.
- `USE_CASE_REGISTRY` in `services/llm_routing.py` is the single place to add a call site; `get_llm_for(use_case)` is the factory tests patch.
- `audit_log` exists (E-5.4) for recording events.
- Q&A composers live in `JobDetailPage.tsx` (`QASection`), `LibraryQAPage.tsx` and `VideoKnowledgePage.tsx` (drawer); `/health` reports feature availability so pages can disable LLM actions.

## Chosen approach

`GET /api/v1/suggestions?context=job:<id>|document:<id>|library` → `{suggestions: [{question, rationale, source}]}` with three to five items:

1. **Candidates from two pools.** (a) Nearest-neighbour *past questions* from `qa_library_global` (query text = job topic or document title plus knowledge topics; tenant-filtered), which is what "learn from past questions" means literally. (b) LLM-generated questions grounded in the context summary (report section headings, or the document's knowledge topics and facts) through a new `qa_suggest_questions` use case on the cheapest configured tier, structured JSON, low reasoning.
2. **Dedupe** against questions already asked on this context (cosine on the same embedder) and against each other.
3. **Diversify** with maximal marginal relevance so the five differ in subject, not just wording. Bing's production work (Rosset et al., WWW 2020) framed the goal as *usefulness* for the next step rather than relevance and measured an 8 % click lift; usefulness is what the rationale field is for.
4. **Cache** per `(tenant, context, latest_exchange_id)` for a configurable window; a re-open costs nothing; a new exchange on the context invalidates.
5. **Measure.** Impressions and clicks as `audit_log` events (`suggestion_shown`, `suggestion_clicked`) so click-through can be reported before the feature is called good.

UI: a "You might ask…" card under the composer on the job page, the library Q&A page and the knowledge drawer; click fills the composer, Shift-click asks immediately; hidden when `/health` reports Q&A down; a no-history user still gets pool (b).

**Cost.** A batch of five is about 1,500 input and 150 output tokens: roughly $0.00014 on gpt-5-nano, $0.0002 on Gemini 2.5 Flash-Lite or Claude Haiku 5.5, $0.0008 on gpt-4.1-mini (list prices 2026-10-19). Ten thousand batches a month on a nano model is about $1.40; batch APIs halve it; a local model via `LLM_USE_CASE_CONFIG` makes it free. Metered under the existing daily LLM-token keys, not a new quota.

## Alternatives rejected

| Option | Why not |
|---|---|
| Past questions only, no generation | A new user has no history; a new topic has no neighbours. |
| Generation only, no history | Ignores the corpus the user explicitly asked to learn from. |
| Suggestions computed at ingest time | Context changes with every exchange; on-demand with a cache is cheaper and fresher. |
| A trained ranker (Bing's approach) | Needs session logs at a scale this app will not have; MMR plus click logging gets the diversity benefit without training. |
| Showing suggestions inside the answer card | Perplexity's "Related" pattern; the composer card keeps the answer card clean and the action obvious. |

## Schema deltas

None persistent. A small `suggestion_cache(tenant_id, context_key, payload_json, computed_at)` table or an in-process TTL cache; the table is preferred so Celery and the API process agree and it survives restarts.

## API deltas

`GET /api/v1/suggestions` as above; `POST /api/v1/suggestions/feedback {context, question, action}` (or direct `audit_log` writes from the click handler through an existing endpoint). Registry: `qa_suggest_questions`.

## Modules touched

`services/suggestion_service.py` (new), `agents/prompts/suggestion_prompts.py` (new), `services/llm_routing.py` (use case), `services/chroma_service.py` (reuse), `routers/suggestions.py` (new), `models/suggestion_cache.py`, `frontend/src/components/qa/SuggestionCard.tsx` (new), `JobDetailPage.tsx`, `LibraryQAPage.tsx`, `VideoKnowledgePage.tsx`, `services/suggestionsApi.ts`.

## Risks

- **Repetition** across contexts if the generator sees the same topics; MMR and the dedupe step are the mitigation, and the click data will show it.
- **Leakage**: the past-question pool must always pass `tenant_id`; the fail-closed filter in `query_qa_collection` covers it, and a test asserts it.
- **Latency**: two Chroma queries plus one LLM call; the cache hides it after the first open; the card renders asynchronously so it never blocks the page.
- **Quality is unmeasured until clicks exist**; log from day one.

## Test strategy

- Service: LLM factory patched; no-history path returns only generated items; history path merges and dedupes; MMR produces distinct subjects on a fixture; cache hit makes no LLM call; invalidation on a new exchange.
- Isolation: two tenants with similar questions, no cross-tenant neighbours.
- Router: context parsing, 404 for a foreign job, hidden when Q&A is down.
- Frontend: type-check; click fills composer; Shift-click asks.

## First PR (S-8.4.1)

The endpoint, service, use case, cache and tests, with the job context only. The card and the other two contexts follow as a frontend-only PR.

## Open questions

1. Should suggestions also appear in the Echo bubble's anticipation cards from the start (E-3.8), or only on the Q&A pages?
2. Cache window: one hour per context is proposed.

## Sources (fetched 2026-10-19)

Rosset et al., "Leading Conversational Search by Suggesting Useful Questions" (WWW 2020, Microsoft Research page); NotebookLM documentation mirror on suggested follow-ups; third-party write-ups of Perplexity "Related"; Carbonell and Goldstein 1998 (MMR); DF-RAG and Salesforce diversity-in-retrieval papers; OpenAI, Google and Anthropic pricing pages. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
