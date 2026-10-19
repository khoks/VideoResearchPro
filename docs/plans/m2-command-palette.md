# M2 — Command palette and global search: plan

**Board:** [E-8.2](../initiatives.md#e-82--command-palette-and-global-search-m2) · **Roadmap:** [M2](../feature-roadmap.md#m2--cmd-k-global-search-) · **Research date:** 2026-10-19 · **Status:** recommendation.

## Problem

Finding anything means navigating to the right page and scanning a list. There is no way to jump to a job by topic, a document by title, a past question, or a channel from wherever the user is, and no keyboard route to the common actions. The roadmap sketched a `Cmd-K` palette over one mixed-type search endpoint.

## Verified current state (2026-10-18)

- No `/api/v1/search` endpoint. The only free-text search is `GET /library/videos?search=` (`ILIKE` on title and channel name, visibility-scoped).
- No keyboard-shortcut hook. `docs/ui-design.md` §2.1 claims `g + r` / `g + l` chords "implemented via a global `useShortcuts` hook"; no such hook exists in `frontend/src`. The only `keydown` handlers are the Modal's Escape and one in `VideoKnowledgePage`.
- Frontend dependencies are `react`, `react-dom`, `react-router-dom`, `@tanstack/react-query`, `zustand`, `axios`, `react-markdown`; styling is inline objects plus a small `index.css`.
- SQLite in the project's venv: Python 3.12.10 with SQLite 3.49.1 reporting `ENABLE_FTS5` (verified by running `PRAGMA compile_options` and creating a trigram FTS5 table). FTS5 is compiled into python.org's Windows and macOS builds and into uv's python-build-standalone; Linux distro Pythons link the system `libsqlite3`, so availability there depends on the image.
- Chroma `query_qa_collection` is tenant-filtered; `query_collection` takes a `video_ids` filter. Both return `distance`.
- Every entity has a tenant anchor: `jobs.tenant_id`, `document_visibility`, `channel_subscriptions`, `*_qa_exchanges.tenant_id`.

## Chosen approach

### Backend

`GET /api/v1/search?q=&types=&limit=&semantic=` returns `{groups: [{type, items: [{id, title, subtitle, href, score}]}]}`.

- **Keyword search on SQLite FTS5** external-content tables (`fts_documents`, `fts_jobs`, `fts_channels`, `fts_qa`, `fts_knowledge`) maintained by `AFTER INSERT/UPDATE/DELETE` triggers, created with `op.execute` in the migration **conditionally**; a startup probe (`'ENABLE_FTS5' in PRAGMA compile_options`, or attempt `CREATE VIRTUAL TABLE` and catch `OperationalError`) decides between FTS5 and a `LIKE` fallback and logs a warning. Tokeniser `unicode61` with `remove_diacritics 2` plus a `trigram` table for substring matching (three-character minimum, case-insensitive, indexed `LIKE`); `bm25()` with column weights (title over body), recency tie-break, per-group cap. Devanagari titles index as tokens without stemming or transliteration folding; the semantic group covers that gap.
- **Tenant scoping** is applied *after* the FTS hit list by joining the entity's tenant anchor, exactly as the library listing does; never a tenant column inside the FTS table.
- **Semantic group (optional, S-8.2.3)**: `qa_library_global` (tenant filter) and the transcript collection (visible set) merged with the keyword lists by **reciprocal rank fusion** (`score = Σ 1/(60 + rank)`), which is rank-only so FTS5 scores and Chroma distances need no calibration. Labelled "Similar" in the palette.
- Entities covered: jobs (topic, instructions), documents (title, description), channels (name), Q&A exchanges (question text), knowledge artifacts (Markdown), shelves and notes once M1 and M5 exist.

### Frontend

- `useShortcuts` hook: `Ctrl/Cmd-K` opens the palette with `Ctrl-Alt-K` as the alternate chord (Chrome on Windows and Linux binds `Ctrl-K` to the address bar; a page handler that calls `preventDefault()` wins once the page has focus, loses during load or when focus is in browser chrome, hence the alternate, as GitHub offers); `Escape` closes; `/` focuses the page's search only when no input is focused and is disable-able in settings (WCAG 2.1 SC 2.1.4, character-key shortcuts). On macOS `Ctrl-K` is emacs kill-line inside text fields, so `Cmd-K` there.
- Palette on **`cmdk`** (MIT, 1.1.1, about 15 kB gzipped including four Radix dependencies, unstyled, React 19 peer dependency; `shouldFilter={false}` so the server does the filtering; `Command.Dialog` composes an accessible Radix dialog and needs a `label`). Selected state is exposed as `data-selected` attributes which inline styles cannot target: read it through `useCommandState` for per-item inline styles, or accept **one scoped `<style>` block** for the palette, an explicit small deviation from the inline-only convention. ARIA combobox with listbox semantics (DOM focus stays in the input, `aria-activedescendant`, script scrolls the active option into view).
- Grouped results, recent items in `localStorage`, navigation actions ("New research", "Open library Q&A", "Toggle theme", "Ask Echo" when Studio), debounced query with request cancellation, loading and empty states, result count announced to screen readers.
- Remove the stale `ui-design.md` claim or make the `g + …` chords real in the same PR.

## Alternatives rejected

| Option | Why not |
|---|---|
| `LIKE`-only search | Full table scans on description and knowledge Markdown; no ranking; FTS5 is present wherever the project is developed and the fallback covers the rest. |
| `kbar` | Went 1.0 on 2026-08-10 but bundles fuse.js and react-virtual (27.5 kB) and ships styled components. |
| `react-cmdk` | No React 19 peer dependency; Tailwind-styled. |
| shadcn `Command` | Requires Tailwind. |
| Client-side fuzzy search (fuse.js, match-sorter, uFuzzy) | Would need the whole catalogue on the client; fine for the navigation actions list only. |
| Chroma `where_document` `$contains` as the keyword engine | Case-sensitive, undocumented whether it is indexed, and it only sees chunk text. |
| RedBeat-style search service or Elasticsearch | A self-host app on SQLite should not need a second engine for a few thousand rows. |

## Schema deltas

Five FTS5 virtual tables with triggers (created conditionally; not SQLAlchemy models); a `search_backend` value recorded at startup. No change to existing tables.

## API deltas

`GET /api/v1/search` as above. `GET /api/v1/health` gains `search_backend: "fts5" | "like"` so the UI can label the fallback.

## Modules touched

`services/search_service.py` (new), one Alembic revision with `op.execute` DDL, `routers/search.py` (new), `main.py` (startup probe), `services/chroma_service.py` (semantic group helper), `frontend/src/hooks/useShortcuts.ts` (new), `frontend/src/components/palette/CommandPalette.tsx` (new), `frontend/src/layouts/AppLayout.tsx` (mount), `frontend/src/services/searchApi.ts` (new), `package.json` (`cmdk`), `docs/ui-design.md` (correct §2.1).

## Risks

- **FTS5 absent on a Linux self-host**: the probe and `LIKE` fallback are mandatory, and the migration must not fail when the virtual table cannot be created.
- **Triggers and bulk writes**: ingest writes thousands of chunk rows but only one `documents` row per source; the FTS triggers fire per document, which is fine; verify on the 200-video job.
- **`cmdk` cadence**: no release since 2025-03-14 and 76 open issues; stable and tiny, but a React 20 break would wait on a volunteer. Fallbacks: Ariakit Combobox or React Aria Autocomplete (licences not verified on-page; believed permissive).
- **Inline-style purity**: the one scoped `<style>` block should be an explicit decision.
- **Hindi and transliteration**: `unicode61` tokenises Devanagari but romanised queries only match via trigram substrings; the semantic group is the safety net.

## Test strategy

- Service: FTS5 path and `LIKE` path both exercised (parametrised fixture forces the fallback); isolation (two tenants, same titles, only own results); bm25 ordering; trigram substring; Devanagari title found by exact token.
- Latency: seeded 5,000 documents and 2,000 exchanges; assert the endpoint answers under 300 ms on both paths.
- Router: `types` filter, `limit` cap, 401 without auth.
- Frontend: type-check; keyboard tests (open, arrow, Enter, Escape, `/` ignored inside inputs); axe-style ARIA assertions in a Playwright smoke.

## First PR (S-8.2.1)

`search_service` with the probe, the FTS5 tables and triggers behind the conditional migration, the `LIKE` fallback, the `/search` endpoint for jobs, documents, channels and Q&A, isolation and latency tests. No palette yet: the endpoint is useful on its own for the library page's search box and lets the UI land as a pure frontend PR.

## Open questions

1. Accept one scoped `<style>` block for the palette, or commit to `useCommandState` for every item style?
2. Should `/` be bound at all, given it conflicts with Firefox Quick Find and needs a settings toggle?

## Sources (fetched 2026-10-19)

npm registry and Bundlephobia for `cmdk`, `kbar`, `react-cmdk`, `fuse.js`, `match-sorter`, `uFuzzy`; the `cmdk` README; shadcn Command docs; Ariakit Combobox and React Aria Autocomplete pages; SQLite compile options and FTS5 documentation; CPython `PCbuild/sqlite3.vcxproj`, `Mac/BuildScript/build-installer.py`, python-build-standalone `build-sqlite.sh`; Simon Willison's FTS5 probe; Chroma full-text search docs; Elastic's reciprocal rank fusion reference and Cormack et al. 2009; Chrome, GitHub, Notion and Slack shortcut pages; the GitHub command-palette deprecation and pause; WAI-ARIA combobox pattern; WCAG 2.1.4. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
