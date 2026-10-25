# L2 — Author Studio: plan

**Board:** [I-6](../initiatives.md#i-6--author-studio-output-generation-l2) · **Roadmap:** [L2](../feature-roadmap.md#l2--author-studio-output-generation-) · **Research date:** 2026-10-19 · **Status:** recommendation; adopt by filing a decision.

## Problem

The library can answer questions; it cannot yet produce anything a reader would take away. The roadmap wants five derivative artifacts (book, site, deck, newsletter, reel) on one grounded source set, each citing the passages it came from. The foundation shipped on 2026-05-05 ([D-044](../decisions.md#d-044--foundation-first-then-concrete-implementations-deferred-for-i-3--i-6-2026-05-05)): the `outputs` table, the `Outputter` Protocol and registry, the `/api/v1/author/*` surface, the Pro+ gate, and one deterministic book outputter. Nothing since.

## Verified current state (2026-10-18)

| Claim | Where | Finding |
|---|---|---|
| `outputs` table | `backend/app/models/output.py`, revision `b5c6d7e8f9a0` | `id, user_id, kind, title, status, source_ids_json, parameters_json, content_text, content_path, error_message, created_at, updated_at`. No `tenant_id` (today `tenant_id == user.id` everywhere, so harmless). No `celery_task_id`. |
| Outputter registry | `backend/app/services/output_service.py` | `Outputter.generate(db, user, output)`, `register_outputter`, `run_generation` with `pending → generating → completed | failed`. |
| Book v1 | `backend/app/services/outputters/book_markdown.py` | Reads each job's HTML report through `report_service.get_report_html`, strips tags with a regex (`_strip_html_to_markdownish`), appends the job's Q&A, writes Markdown to `content_text`. Raises `OutputError` on an empty `source_ids` list. |
| REST | `backend/app/routers/author.py` | `GET /kinds`, `POST /outputs` (creates **and generates synchronously inside the request**; 501 for kinds without an outputter), `GET /outputs`, `GET /outputs/{id}`, `GET /outputs/{id}/content` (text only), `DELETE`. No download route, no citations route, no cancel. |
| `/author` page | `frontend/src/pages/AuthorPage.tsx` | At audit time (2026-10-18) the stub posted `{kind: 'book', title}` with **no `source_ids`**, so every book created from the UI landed as `failed`. PR #224 (2026-10-19, [D-069](../decisions.md#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19)) replaced it with a chapter picker over finished runs, an outputs list, a reader modal, download and delete; the four other kinds render as "coming later". |
| `output_citations` table | — | Sketched in the roadmap, never built. |
| Report source format | `backend/app/agents/prompts/report_prompts.py`, `utils/html_builder.py` | The compose prompt emits semantic HTML sections; `html_builder` wraps them with a `<style>` block and a statistics grid and `save_report` writes one file at `jobs.report_path`. **There is no Markdown source.** |
| Scheduler | `backend/app/tasks/celery_app.py` | No beat configured; nothing in the app runs on a schedule. |
| Email | `backend/app/services/email_service.py` | `send_email(to, subject, body)` with SMTP or log fallback; plain text body only. |
| Media tooling | `backend/app/services/frame_service.py` | ffmpeg and yt-dlp already shelled out to; Playwright is an optional dependency (`requirements-spa.txt`). |
| Frames | `backend/app/models/visual_frame.py` | R1 stills exist per document under `VISUAL_FRAMES_DIR` when `visual_analysis` was on. |

## Chosen approach

**Order:** book → generation runtime → site → deck → newsletter → reel. Books first because every other kind reuses their pieces (Markdown source, citation contract, async generation, downloads); reels last because they need a TTS provider and carry the only legal risk.

### Shared pieces (E-6.7, S-6.1.2)

1. **Markdown source for reports.** `report_service.report_markdown(job)` converts the stored HTML body with **markdownify** (MIT) through a small `MarkdownConverter` subclass that keeps `&t=` citation links, renders `[VISUAL @ mm:ss]` spans consistently and emits ATX headings; cached at `<report_path>.md`. The book, the site's text search index, the newsletter's plain-text part and the Markdown export route all read it. `html2text` is rejected (GPL-3.0-or-later); trafilatura's Markdown mode is a boilerplate stripper and drops report content.
2. **Async generation.** `generate_output` Celery task dispatched through `task_routing_service.dispatch_for_user`; progress on `job_progress:{output_id}` so the existing WebSocket manager and `useJobProgress` need no new channel; `POST /outputs` returns `pending` at once (a `sync=true` query keeps the test path). Outputs gain `celery_task_id`.
3. **Binary artifacts.** `OUTPUTS_DIR/<tenant>/<output_id>/`, path-traversal guard copied from `frame_service`, `GET /outputs/{id}/download` streaming with media type by kind.
4. **Citations.** `output_citations(id, output_id, document_id, source_type, source_id, url, label, position)` written by one helper every outputter calls; `GET /outputs/{id}/citations`. This is the differentiator: none of the AI deck or audio products researched document per-slide or per-scene citations.

### Book (E-6.1)

- **Source picker** (S-6.1.1): shipped by PR #224 the day after the audit; what remains is the job-page shortcut, the server-side empty-`source_ids` guard and counts on the outputs list.
- **Cohesion** (S-6.1.3): two use cases. `author_book_outline` reads chapter summaries and returns order, part grouping, transition briefs, introduction and conclusion briefs as JSON; `author_book_prose` writes the front and back matter, transitions and a glossary. **Chapter bodies are never rewritten by the LLM**, so citations cannot be invented (the S-1.14.9 class of defect). `parameters_json.cohesion ∈ {none, light, full}`; `none` is the shipped v1. `VISUAL_ANNOTATION_CONTRACT` and the English-output contract ([D-066](../decisions.md#d-066--language-contract-temporal-awareness-and-corpus-aware-qa-length-2026-07-31)) are injected. Failed calls are disclosed in the manuscript (the [D-056](../decisions.md#d-056--report-pipeline-budgets-derived-from-work-lossless-reduce-sectioned-compose-2026-07-30) posture).
- **Endnotes** (S-6.1.4): every link in the chapter Markdown becomes a numbered endnote carrying title, channel, timestamp and URL and an `output_citations` row.
- **PDF** (S-6.1.5): **WeasyPrint** (BSD-3-Clause, v70.0 of 2026-09-08). It consumes HTML directly, needs no Node or Chromium, and is the only candidate with the CSS Paged Media and GCPM features a book needs: running chapter headers via `string-set`, footnotes via `float: footnote`, a PDF outline from headings, named front-matter pages. Markdown → HTML through `python-markdown` or `markdown-it-py` (both permissive) with the reader stylesheet from M8. Windows developers install MSYS2 Pango once (`pacman -S mingw-w64-ucrt-x86_64-pango`, `WEASYPRINT_DLL_DIRECTORIES`); Linux needs `libpango-1.0-0 libpangoft2-1.0-0`. Playwright's `page.pdf()` (Apache-2.0, already optional) is the fallback only; Chromium has no running headers or footnotes.
- **EPUB** (S-6.1.5): **hand-rolled EPUB 3** with `zipfile`, lxml (BSD-3-Clause) and Jinja2: `mimetype` first and uncompressed, `META-INF/container.xml`, `content.opf`, `nav.xhtml`, XHTML chapters serialised from the same HTML. About 200 to 300 lines, zero new runtime dependencies. EPUBCheck (Java) runs in CI only.
- **Optional install.** Both converters live in `requirements-author.txt`; the outputter returns 501 with install instructions when they are missing, the Playwright precedent.

### Site (E-6.2)

An **in-process Jinja2 static export**, not Astro or 11ty. Inputs are database rows and HTML, so every static-site generator would first need a synthetic source tree and then a Node runtime (Astro, 11ty, Quartz are MIT but need Node) or a copyleft binary (Pelican is AGPL-3.0-or-later; Zola's post-0.22 code is EUPL-1.2). Templates under `app/templates/site/`: index, one page per report, one per document with its knowledge report and citations, tag and topic pages, backlinks computed from citations, a pre-built `search.json` with a vendored MiniSearch or Lunr (MIT, no CDN), one CSS file from the `theme.ts` tokens. Output is a zip; optionally mounted under `/sites/<tenant>/…` by FastAPI `StaticFiles` behind the existing auth. MkDocs (BSD-2-Clause, Python) is the upgrade path if a theme ecosystem is ever wanted; Pagefind (MIT, Rust binary) if search must scale past hundreds of pages. Publishing to GitHub Pages or Netlify is a later story.

### Deck (E-6.3)

**python-pptx** (MIT, 1.0.2 of 2024-08-07, stable). `author_deck_outline` emits `{title, slides: [{heading, bullets, speaker_notes, citations: [{document_id, timestamp, quote}]}]}`; the renderer uses one editorial layout master from `docs/branding.md` tokens; citations go into speaker notes with the `&t=` link and a closing Sources slide. The roadmap's `anthropic-skills:pptx` is a Claude Code harness skill and cannot be called from the worker. Preview rendering would need LibreOffice headless; skip it, download the file.

### Newsletter (E-6.4)

Content is deterministic except the featured section: documents, exchanges and outputs newer than `since` and visible to the tenant; `author_newsletter_compose` writes only the featured deep-dive. Delivery runs on the **scheduler M3 builds** (S-8.3.1: one static Celery beat entry, a tick every five minutes, due rows in a table). `newsletter_subscriptions(id, tenant_id, cadence, sections_json, last_issue_at, enabled)`; a `(subscription_id, period_key)` unique sends table makes delivery idempotent (`INSERT … ON CONFLICT DO NOTHING` before rendering; deterministic `Message-ID`). Email is a Jinja2 table-layout template inlined with **premailer** (BSD-3-Clause), plain-text alternative from markdownify, sent through the existing `email_service`. Readwise's daily review is the pattern worth copying: the digest resurfaces *the user's own library*, not new content.

### Reel (E-6.5)

Narration over **stills the app already owns**: R1 `visual_frames`, generated title and quote cards, source thumbnails, captions burned in, a sources end-card; 1080×1920 at 30 fps, H.264, `yuv420p`, captions kept out of the top 12–15 % and bottom 20–25 % that platform chrome covers. Assembled with the **ffmpeg `filter_complex`** pipeline already in-tree (moviepy, MIT, is alive but slow-moving and only wraps ffmpeg; Remotion is source-available with a company licence and needs Node plus Chromium). TTS behind a `tts_service` abstraction configured like `llm_routing`: default hosted `openai:gpt-4o-mini-tts`, `google:chirp3-hd` for `hi-IN` and `en-IN` narration, local **Chatterbox Multilingual V3** (MIT, Hindi pack) for self-host. Kokoro (Apache-2.0) self-rates its Hindi voices C and needs GPL `espeak-ng` for Hindi; Piper's successor is GPL-3.0; Coqui the company closed in January 2024 and the XTTS weights are non-commercial.

**No third-party footage by default.** YouTube's Terms of Service (effective 2023-12-15) forbid downloading except where YouTube provides it, and re-publishing clips is a copyright exposure where fair use is a defence argued case by case, not a licence. A product that automates it for many users faces takedowns on the outputs and secondary-liability arguments. The roadmap's "clip-stitched B-roll from source videos" is therefore out of v1; if the user wants it, record the risk as a decision and gate it per render with the statement in the UI.

## Alternatives rejected

| Option | Why not |
|---|---|
| `anthropic-skills:docx` / `pptx` for PDF and decks | Harness skills, not libraries; the worker cannot call them. |
| pandoc as the PDF or EPUB engine | GPL-2.0-or-later binary. Subprocess use is the mainstream-safe reading, but redistributing it (installer, Docker image) creates source-offer obligations, and pandoc is not a PDF engine anyway (it shells out to one). Acceptable only auto-detected on PATH, like Scrivener does; never required. |
| `ebooklib` for EPUB | AGPL-3.0-or-later on PyPI; importing it into a network-served app triggers §13 for the whole app. |
| `html2text` for Markdown | GPL-3.0-or-later. |
| Typst | Apache-2.0 and fast, but the input is Typst markup, not HTML; getting there means pandoc. |
| Astro / 11ty site | Node runtime in a Python self-host install; comparable projects ship prebuilt assets precisely to avoid it. `nodejs-wheel-binaries` (MIT) exists but adds a second package manager and supply chain. |
| Pelican | AGPL-3.0-or-later. |
| RedBeat / APScheduler for the newsletter | RedBeat (Apache-2.0) only matters for highly available beat; APScheduler 4 is still alpha ("do not use in production"); `django-celery-beat` is Django-only. One static beat entry plus table rows is enough and adds no dependency. |
| moviepy / Remotion | moviepy wraps ffmpeg and pushes frames through numpy (slow at 1080×1920); Remotion's company licence ($25 per seat per month for four or more people) plus Node and Chromium. |
| ElevenLabs as the default TTS | $80 per million characters at the API rate versus $15–30 for OpenAI and Google HD; keep it as an optional provider. |
| Clip-stitched B-roll | Terms-of-Service and copyright exposure above. |

## Schema deltas

- `outputs`: add `celery_task_id`, `progress_pct`, `progress_message`, `tenant_id` (backfilled `= user_id`).
- New `output_citations(id, output_id FK, document_id NULL, source_type, source_id, url, label, position, created_at)`.
- New `newsletter_subscriptions(id, tenant_id, cadence, hour, weekday, timezone, sections_json, last_issue_at, enabled, created_at)` and `newsletter_sends(subscription_id, period_key, status, message_id, sent_at, UNIQUE(subscription_id, period_key))`.
- `scheduled_runs` comes from M3 (S-8.3.1), not here.

## API deltas

- `POST /author/outputs` returns `pending` immediately; `?sync=true` for tests.
- New: `GET /author/outputs/{id}/download`, `GET /author/outputs/{id}/citations`, `POST /author/outputs/{id}/cancel`, `GET /jobs/{id}/report.md`.
- `source_ids` accepts `job:<id>`, `shelf:<id>` (after M1), `document:<id>`; every id is resolved through the tenant's ownership or visibility.
- Newsletter: `GET/PUT /author/newsletter` (subscription), `POST /author/newsletter/preview`.
- New registry use cases: `author_book_outline`, `author_book_prose`, `author_deck_outline`, `author_newsletter_compose`, `author_reel_script`; a new `tts_service` with its own provider config.

## Modules touched

`services/output_service.py`, `services/outputters/*` (new: `book_pdf.py`, `book_epub.py`, `site_static.py`, `deck_pptx.py`, `newsletter.py`, `reel.py`), `services/report_service.py` (Markdown), `services/tts_service.py` (new), `routers/author.py`, `tasks/output_tasks.py` (new; `celery_app` autodiscover gains it), `agents/prompts/author_prompts.py` (new), `services/llm_routing.py` (registry entries), `app/templates/site/*` and `app/templates/book/*` (new), `frontend/src/pages/AuthorPage.tsx`, `frontend/src/hooks/useJobProgress.ts` (output subscriptions), `scripts/start.ps1` (beat process, via M3), `requirements-author.txt` (new).

## Risks

- **Copyleft in `requirements.txt`.** The traps found: ebooklib, html2text, Pelican, piper1-gpl, espeak-ng, YAKE. `pymupdf` (AGPL-3.0) is already there and is a pre-existing SaaS-path question of its own.
- **WeasyPrint on Windows** needs MSYS2 Pango and is a known antivirus false positive; CI and Docker on Linux are simple. Decide whether `start.ps1` checks `WEASYPRINT_DLL_DIRECTORIES`.
- **Hindi and Hinglish narration quality is unmeasured** by every model card read. A listening test on the project's own corpus (Devanagari and romanised) must precede choosing a non-English default voice.
- **`gpt-4o-mini-tts` status.** OpenAI's model page shows no deprecation (snapshot 2025-12-15), one third-party calculator claims one; the model name must be configuration, not code.
- **Cost of cohesion.** At list prices fetched 2026-10-19, a cohesion pass over ten 5,000-word reports (about 262k input, 78k output tokens) costs roughly $1.1 on gpt-5, $1.7 on Sonnet 5.5, $1.8 on gpt-5.4, $3.4 on Opus 5.5, $0.22 on gpt-5-mini. Output tokens dominate; put the shared outline prefix first and use prompt caching; convert to Markdown *before* the pass so tags are not paid for. Measure real token counts before fixing the registry entries. Deck, newsletter and reel scripts are each a few cents; TTS adds $0.14–0.72 per ten minutes.
- **Single beat process.** Two beats double the tick load; `start.ps1` must run exactly one.
- **Synchronous v1 path.** Until S-6.7.1 lands, a slow outputter blocks the request; ship the runtime before cohesion.

## Test strategy

- Unit: markdownify subclass round-trips three stored real reports (headings, links, tables, `[VISUAL @]` spans survive); EPUB container validity (zip order, `mimetype` first); PDF page count and an embedded Devanagari glyph; python-pptx file opens and every content slide has notes; newsletter `since` boundary and the empty-issue skip; idempotent send on duplicate `period_key`; reel duration within budget and `ffprobe` validity on a two-scene fixture.
- Router: `.delay()` mocked at the router boundary (the conftest pattern); cross-user 404 on download; traversal rejected; 400 on empty `source_ids` for books; 501 with install text when a converter is absent.
- Agent: LLM factory patched; golden outline on a two-job fixture; failed prose call disclosed in the manuscript.
- Frontend: type-check; Playwright smoke for pick → generate → progress → download.
- Quality: the book cohesion pass judged blind against the `none` baseline with the E-1.14 method before `full` becomes the default.

## First PR (S-6.1.2, the Markdown source)

With the picker already shipped (PR #224), the first new PR is the shared enabler: `report_service.report_markdown(job)` on markdownify with the citation-preserving converter subclass, cached beside the HTML; `BookMarkdownOutputter` reads it instead of the tag-stripping regex; `GET /jobs/{id}/report.md`; round-trip tests on three stored real reports. The small S-6.1.1 remainder (400 guard, job-page shortcut, counts) can ride along or follow. No schema change.

## Open questions (the user's call)

1. **Self-host TTS default.** Local Chatterbox (MIT, Hindi pack, needs a GPU-class machine for speed) or hosted OpenAI by default with local as opt-in?
   **Answered 2026-10-25** by [D-112](../decisions.md#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25): reels (E-6.5) are deferred; when built, hosted TTS is the default, local TTS is opt-in, and a Hindi listening test is part of the work.
2. **B-roll.** The plan drops third-party footage from v1 for the Terms-of-Service and copyright reasons above. Should an explicit, per-render opt-in with the risk shown ever exist?
   **Answered 2026-10-25** by [D-112](../decisions.md#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25): no B-roll.
3. **Book templates.** The roadmap asked single editorial template first; agreed. Academic and journalistic variants later?
   **Deferred 2026-10-25** by [D-112](../decisions.md#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25): academic and journalistic book template variants are deferred.
4. **Hosted site preview.** Download-only first (as the roadmap recommends); mounting under the app's own origin is cheap but makes the app a public host once M11 exists.
   **Deferred 2026-10-25** by [D-112](../decisions.md#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25): sites stay download only, a hosted preview under the app's origin waits, and one-click publishing (S-6.2.2) will not be built.

## Sources (fetched 2026-10-19)

WeasyPrint docs and PyPI (first steps, API reference, issue #2105); pandoc COPYRIGHT and pypandoc PyPI; Typst PyPI; Playwright Python `page.pdf`; EbookLib PyPI (AGPL); markdownify and html2text PyPI; MkDocs, Pelican, Zola, Astro, 11ty, Quartz repositories; `nodejs-wheel-binaries` PyPI; python-pptx PyPI and docs; Celery periodic-tasks docs; RedBeat, croniter (pallets-eco), APScheduler PyPI; premailer and `mjml-python` repositories; OpenAI pricing and `gpt-4o-mini-tts` model page; ElevenLabs API pricing; Google Cloud TTS pricing and Chirp 3 HD docs; Kokoro-82M model card; `OHF-Voice/piper1-gpl`; `idiap/coqui-ai-TTS`; `resemble-ai/chatterbox`; `nari-labs/dia`; moviepy PyPI and releases; Remotion LICENSE; YouTube Terms of Service; Anthropic pricing; NotebookLM, Perplexity Pages, Readwise and Obsidian Publish pricing pages. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
