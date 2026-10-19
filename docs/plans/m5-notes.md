# M5 — Notes, the user's own voice in the library: plan

**Board:** [E-8.5](../initiatives.md#e-85--notes--the-users-own-voice-in-the-library-m5) · **Roadmap:** [M5](../feature-roadmap.md#m5--notes-user-annotations-) · **Research date:** 2026-10-19 · **Status:** recommendation.

## Problem

The vision says the user's own notes, opinions and Q&As become first-class citizens in the library, cited as "you said this on 2026-03-15". Nothing lets the user write anything down. Notes are also the single richest input for Echo's voice capture (`personal-brain.md` Domain 3 ranks them first) and the roadmap's L4 sketch gives them a 1.5× retrieval weight.

## Verified current state (2026-10-18)

- No `notes` table, model, router or UI.
- Retrieval: `chroma_service.query_collection` over the shared transcript collection with a `video_ids` filter; `qa_library_global` is a second collection with one document per exchange and a tenant filter (the pattern to copy). Neither collection sets `hnsw:space`, so both use Chroma's default squared-L2 distance.
- Re-ranking: [D-068](../decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18) pre-registered `distance / weight` after the raw threshold over a 3× pool for channel trust weights; the implementation is [E-7.1](../initiatives.md#e-71--trust-weighted-retrieval-v1), sequenced after the R3/R4 batch that is rewriting `qa_agent.py`. Notes reuse that mechanism and therefore land after it.
- Citations: `qa_agent._chunk_to_reference` is polymorphic by `source_type`; `<CitationLink>` in `frontend/src/components/citation/` dispatches by `Reference.source_type`.
- Prompt contracts: `VISUAL_ANNOTATION_CONTRACT` in `agents/prompts/shared.py` is the precedent for telling the model what machine-inserted text is ([D-067](../decisions.md#d-067--visual-understanding-separate-frames-table-marker-in-text-annotation-opt-in-per-job-2026-07-31)).
- `react-markdown` is already a dependency (Q&A answers, knowledge reports).
- Exports: `services/dataset_service.py` streams JSONL per tenant.

## Chosen approach

- **Data model, W3C-shaped.** `notes(id, tenant_id, target_type, target_id, selector_json, body_md, motivation, created_at, updated_at, deleted_at)`. `target_type` ∈ {document, job, qa_exchange, library_qa_exchange, qa_history_exchange, channel, knowledge_artifact}; `selector_json` optional, following the Web Annotation Data Model's `TextQuoteSelector` (exact, prefix, suffix) plus `start_seconds`, so a note can anchor to a transcript span and carry a `&t=` link exactly like a Q&A citation; `motivation` ∈ {commenting, highlighting, tagging}; `deleted_at` so exports can carry deletions (Readwise's `includeDeleted`). Tags reuse M1's `taggings`.
- **Editor: a plain `<textarea>` with a Markdown preview** through the existing `react-markdown`, zero new bytes. Tiptap v3 core is MIT but StarterKit is 106 kB gzipped and its paid parts are cloud features; Lexical is MIT at 63 kB. Either is a later upgrade if inline formatting is wanted.
- **Private retrieval collection.** A separate `notes_global` Chroma collection (same embedder, one document per note, not chunked, `tenant_id` / `target_type` / `target_id` / `note_id` metadata, queried with the fail-closed tenant filter that `query_qa_collection` uses). Notes are private per tenant while the transcript collection is shared and keyed per video, so mixing them would push a tenant filter into every transcript query and complicate deletes.
- **Merge and weight.** The job and library retrieval paths query both collections and merge by raw distance; the D-068 formula applies with `NOTE_RETRIEVAL_WEIGHT = 1.5` *after* the raw relevance threshold, so an off-topic note cannot be pulled in. Dividing a squared-L2 distance by 1.5 is monotone but not a 1.5× cosine boost; keep the formula for consistency with channel weights and **measure** with the E-1.14 blind-judge method before tuning. Switching new collections to `cosine` is possible; the existing transcript collection cannot change space without re-embedding.
- **Citation.** `_chunk_to_reference` emits `{source_type: "note", note_id, target, created_at, quote}`; `<CitationLink>` renders "you wrote this on YYYY-MM-DD" and links to the note's target. Prompts that read note text carry a marker contract like D-067's (`[NOTE by you, YYYY-MM-DD]`) so the model never attributes the user's words to a speaker.
- **Views and export.** Inline note lists on `VideoRow`, `JobDetailPage`, answer cards, `ChannelRow` and the knowledge drawer; a `/notes` page newest-first with filters; `GET /exports/notes.jsonl` (JSON-LD with the `anno.jsonld` context) and `/exports/notes.md`, streamed like the dataset exports, which is also the GDPR Article 20 "structured, commonly used, machine-readable format" obligation for user-provided data.
- **Echo hook.** Notes count toward the Domain 3 readiness feeder (S-3.5.1) and are the first input to signal extraction (S-3.3.2).

## Alternatives rejected

| Option | Why not |
|---|---|
| Notes as chunks inside the shared transcript collection with `source_type=note` | Private rows in a shared collection; every transcript query would need an added tenant clause; deletes and re-embeds fight the per-video id scheme. |
| Notes as `documents` rows with a visibility grant | Elegant reuse of the pipeline, but it turns a private annotation into a library "source" with transcript-cache semantics and knowledge extraction; a note is not a source. |
| Rich-text editor in v1 | 63–106 kB for formatting the user can write in Markdown. |
| Free-form `target` string | Closed `target_type` set is what makes existence checks through visibility and ownership possible. |
| Weight as a filter or boost before the threshold | Rejected by D-068 for the same reasons. |

## Schema deltas

`notes` as above, with `INDEX(tenant_id, target_type, target_id)` and `INDEX(tenant_id, created_at)`; Chroma `notes_global`.

## API deltas

```
GET/POST           /api/v1/notes                  (?target=document:<id>)
GET/PUT/DELETE     /api/v1/notes/{id}
GET                /api/v1/exports/notes.jsonl | notes.md
```

Settings: `NOTE_RETRIEVAL_WEIGHT` (1.5), `CHROMA_NOTES_COLLECTION_NAME`. Search group `notes` in M2.

## Modules touched

`models/note.py`, one Alembic revision, `services/note_service.py` (new), `services/chroma_service.py` (notes collection, upsert, delete, backfill on worker start like `backfill_qa_library`), `agents/qa_agent.py` (merge, weight, reference emission; after E-7.1), `agents/prompts/shared.py` (`NOTE_ANNOTATION_CONTRACT`), `routers/notes.py` (new), `routers/exports.py`, `services/dataset_service.py`, `frontend/src/components/notes/*` (new), `VideoRow.tsx`, `JobDetailPage.tsx`, `LibraryQAPage.tsx`, `ChannelRow.tsx`, `VideoKnowledgePage.tsx`, `frontend/src/pages/NotesPage.tsx`, `components/citation/CitationLink.tsx`, `types/qa.ts`.

## Risks

- **Sequencing.** The retrieval story depends on E-7.1 landing the re-rank and on the R3/R4 prompt batch finishing in `qa_agent.py`; the schema, UI and export stories do not and can ship first.
- **Privacy in retrieval**: the notes collection must always be queried with `tenant_id`; an empty visible set must still return only the tenant's own notes and nothing else.
- **Prompt contamination**: without the marker contract the answer LLM may quote the user's note as a speaker's claim.
- **Weight semantics** on squared-L2 (above); pre-register the measurement.
- **Backfill on restart** of a large notes corpus is cheap (unchunked, one vector each) but must be idempotent.

## Test strategy

- Service and router: CRUD, isolation (foreign target or note 404), target existence through visibility and ownership, soft delete, export round-trip (JSON-LD context, deletions included).
- Retrieval: a note is cited for a question it answers; ordering versus an equally relevant transcript chunk; absent for other tenants; empty visible set still returns the tenant's notes only when they match; delete removes the vector; the marker contract present in the prompt (a `test_prompt_contracts` case).
- Frontend: type-check; add → inline list → notes page → export smoke.
- Quality: the weighted-versus-unweighted comparison with the E-1.14 method before `NOTE_RETRIEVAL_WEIGHT` is tuned.

## First PR (S-8.5.1)

`notes` table, `note_service`, CRUD routes with target checks, the inline note control and list on documents and jobs, Markdown preview with `react-markdown`, isolation tests. No embedding yet. Immediately useful, and it starts accumulating the text Echo's voice capture needs.

## Open questions

1. Keep the 1.5 weight from the L4 sketch as the starting value, or start at 1.0 and let the measurement set it?
2. Should notes on a *document* be visible on every job that contains the document (recommended: yes, they are about the document)? **Taken at the default in S-8.5.1** (one note stream per `document_id`; a run-scoped thought is a `job` note). See [D-074](../decisions.md#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19); the user may revisit.

## Sources (fetched 2026-10-19)

W3C Web Annotation Data Model (Recommendation 2017-02-23); Apache Annotator selector notes; Hypothes.is API reference (OpenAPI); Readwise Highlights API v2; Zotero notes help; Obsidian link syntax; Tiptap, Lexical and Milkdown repositories and Bundlephobia; Chroma collection configuration (`hnsw:space`); D-067 and D-068 in `decisions.md`; GDPR Article 20. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
