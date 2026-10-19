# M9 — Citation graph and knowledge map: plan

**Board:** [E-8.9](../initiatives.md#e-89--citation-graph-and-knowledge-map-m9) · **Roadmap:** [M9](../feature-roadmap.md#m9--citation-graph--knowledge-map-) · **Research date:** 2026-10-19 · **Status:** recommendation.

## Problem

The library's shape is invisible: which documents the user's questions keep citing, which channels cluster around which topics, what connects to what. The roadmap sketched a force-directed graph of Q&As citing documents, documents to topics, and topic clusters. The known failure mode of such views is the hairball.

## Verified current state (2026-10-18)

- Edges that exist in data today: Q&A exchange → document (structured `references` on `qa_exchanges`, `library_qa_exchanges`, `qa_history_exchanges`), document → channel (`documents.channel_id`), document → topic (`extracted_knowledge_json.topics` where extraction ran), job → document (`job_documents`).
- Edges that must be derived: topic ↔ topic (co-occurrence within documents), Q&A ↔ topic.
- Tenant anchors for every node type exist (`document_visibility`, `channel_subscriptions`, `*_qa_exchanges.tenant_id`).
- No graph library in the frontend; inline styles only; Vite 8 warns at 500 kB per chunk and the critical path budget is about 170 kB gzipped, so the graph must be a lazy route.
- Scale: hundreds to low thousands of documents per tenant, hundreds of exchanges, tens to hundreds of topics; **under 5,000 nodes** in practice.

## Chosen approach

- **Endpoint** `GET /api/v1/library/graph?focus=&depth=&shelf_id=&channel_id=&types=&limit=` → `{nodes, edges, truncated, summary}`: nodes for visible documents, subscribed channels, the tenant's exchanges and topics above a frequency floor; edges from the data above plus derived co-occurrence; degree and recency choose nodes under the cap; stable ids; a one-paragraph `summary` ("312 documents, 48 topics, 6 clusters; largest cluster …") for the textual alternative. Computed per request at this scale (no `graph_edges` table until it proves slow).
- **Local graph first** (the Obsidian model): the default view is the neighbourhood of the current document, exchange or channel at depth 1–2 with a depth slider; the global view is opt-in. Size by degree, colour by Louvain community **plus** a label or shape so colour is never the only channel (WCAG 1.4.1); filters by node type, channel, shelf and date; degree-1 leaves hidden by default; edges per node capped by weight; labels on hover or zoom; click focuses and opens a side card with links to the document, job or exchange; double-click re-centres; layout frozen after convergence.
- **Library**: `sigma` 4 + `graphology` + `@react-sigma/core` + `graphology-layout-forceatlas2` (web-worker layout, Barnes–Hut) + `graphology-communities-louvain`, all MIT, about 113 kB gzipped as a **lazy route chunk**; WebGL headroom far beyond the real node count. `react-force-graph-2d` (MIT, 60 kB, canvas, d3-force under the hood) is the smaller alternative if a simpler API is preferred; both are acceptable, the choice is API ergonomics, not capacity.
- **Accessibility is real work**, not polish: a canvas has no DOM. Ship (a) an equivalent node and edge table view, (b) keyboard navigation over nodes (Tab into the graph, arrows to neighbours, Enter opens) with a focus ring drawn on the canvas, (c) button alternatives to pan, zoom and drag (WCAG 2.2 SC 2.5.7), (d) the textual summary. The table doubles as the narrow-screen fallback.
- **Reuse**: M7's concept graph is this component filtered to a channel; shelf filtering reuses M1's resolution to a document set.

## Alternatives rejected

| Option | Why not |
|---|---|
| `reagraph` (Apache-2.0), `@antv/g6` (MIT) | 385–400 kB gzipped; too heavy for a lazy route in this app. |
| `react-force-graph` umbrella | Adds three.js (about 230 kB gzipped); install the 2D package only if that route is chosen. |
| `cytoscape` (MIT, 137 kB) | Fine, with a WebGL preview since 3.31; chosen against on bundle and React ergonomics. |
| `vis-network` | Dual-licensed and fine, but no advantage. |
| SVG with `d3-force` alone (ISC, 6 kB) | Best accessibility (DOM text) and the right answer under about 500 nodes; interaction gets sluggish around 2,000; keep as the fallback renderer if the library is later dropped. |
| Global hairball by default | The documented pain point in Obsidian's forums; local-first with a depth slider is the mitigation. |
| Persisting a `graph_edges` table from the start | Premature under 5,000 nodes. |

## Schema deltas

None in v1.

## API deltas

`GET /api/v1/library/graph` as above.

## Modules touched

`services/graph_service.py` (new), `routers/library.py` (graph route), `frontend/src/pages/GraphPage.tsx` (lazy, new), `components/graph/{GraphCanvas,GraphTable,GraphControls}.tsx` (new), `routes/index.tsx` (`React.lazy`), `vite.config.ts` (`build.rolldownOptions` manual chunk; Vite 8 is on Rolldown and `rollupOptions` is a deprecated alias), `package.json`.

## Risks

- **Hairball**: mitigated by local-first, caps and filters; still needs a user to try it on a real library.
- **Accessibility scope**: budget it or the page fails 1.1.1, 2.1.1 and 2.5.7.
- **Derived edges**: topic co-occurrence over a large library is quadratic per document in the number of topics; cap topics per document and use a frequency floor.
- **Bundle**: 113 kB only as a lazy chunk; check `manualChunks` under Rolldown.

## Test strategy

- Service: isolation (no foreign nodes), cap and truncation flag, focus mode depth, derived edges on a fixture, summary text.
- Frontend: type-check; the table view renders the same node set as the canvas (a data-level assertion); keyboard navigation smoke in Playwright; reduced-motion disables the animated layout.

## First PR (S-8.9.1)

The graph endpoint and service with isolation and cap tests, returning nodes, edges and the summary. The UI follows as its own lazy-route PR.

## Open questions

1. `sigma` (richer, 113 kB, WebGL) or `react-force-graph-2d` (simpler, 60 kB, canvas)?
2. Should the global view exist in v1 at all, or local graphs only until the hairball question is answered on real data?

Taken at their defaults in S-8.9.2 (2026-10-19), both still the user's to revisit: **sigma** (used directly, without `@react-sigma/core`); the **global view ships**, capped at 300 nodes with single-link nodes hidden, and the local view opens from any node, channel or run.

## Sources (fetched 2026-10-19)

npm and Bundlephobia for `d3-force`, `react-force-graph-2d`, `sigma`, `graphology`, `@react-sigma/core`, `graphology-layout-forceatlas2`, `graphology-communities-louvain`, `cytoscape`, `react-cytoscapejs`, `vis-network`, `reagraph`, `@antv/g6`; cytoscape 3.31 WebGL preview post; graphology layout docs; Obsidian graph view help and forum; KeyLines and Oracle accessibility guidance; Vite build options; WCAG 2.2. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
