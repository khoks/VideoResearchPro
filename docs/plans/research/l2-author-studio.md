# L2 "Author Studio" — library, licence and prior-art research

Research date: 2026-10-19. Facts verified against primary pages (PyPI metadata, GitHub licence sidebars, vendor pricing pages, official docs) wherever a fetch succeeded; items that rest on secondary sources only are marked **[secondary]**, and items I could not verify at all are marked **[unverified]**. Nothing here is legal advice.

Scope reminder: the backend is Python 3.12 / FastAPI / Celery / SQLite with Jinja2, an `outputs` table + Outputter registry, SMTP via `email_service.py`, ffmpeg + yt-dlp already present (`frame_service.py`), Playwright already an optional dependency, LangChain clients for OpenAI / Anthropic / Google. The source material for every output kind is the existing LLM-generated **semantic HTML report** (no Markdown source). "anthropic-skills:docx / pptx" are Claude Code harness skills, not server libraries — treated as unavailable throughout.

---

## Summary

1. **PDF: WeasyPrint** (BSD-3-Clause, v70.0 of 2026-09-08). Pure Python + Pango, no Node, no Chromium, and the only candidate with the full CSS Paged Media + GCPM feature set a book needs (running headers via `string-set`, footnotes, PDF outline from h1–h6, named pages). Our source is already HTML, so no Markdown round-trip. Windows dev needs MSYS2 Pango once.
2. **EPUB: hand-rolled EPUB 3 zip** (`zipfile` + lxml BSD-3-Clause + Jinja2). **ebooklib is AGPL-3.0-or-later** (confirmed on PyPI) — importing it into a network-served app drags the whole app under AGPL §13; reject. pandoc (`-t epub3`) is a GPL-2.0-or-later *binary*: fine to call as a subprocess, not fine to make a hard dependency or bundle casually.
3. **HTML → Markdown: markdownify** (MIT). html2text is **GPL-3.0-or-later** (PyPI licence expression) — reject on licence. trafilatura (Apache-2.0 since 1.8.0) has a Markdown mode but is a boilerplate *stripper*; it will drop report content.
4. **Site: no SSG at all.** Render the wiki with the Jinja2 already in the app into a static folder (index, report pages, document pages, tags, backlinks, JSON search index + MiniSearch/Lunr MIT). Astro/11ty need Node (both MIT); Pelican is AGPL-3.0-or-later; Zola's post-0.22 code is EUPL-1.2 (a separate binary, acceptable but unnecessary); MkDocs (BSD-2-Clause, Python) is the fallback if a theme ecosystem is ever wanted. Node can be pip-installed (`nodejs-wheel-binaries`, MIT) but comparable self-hosted Python apps ship pre-built assets precisely so users never need Node.
5. **Slides: python-pptx** (MIT, v1.0.2 of 2024-08-07, stable, no newer release). LLM emits a slide-spec JSON; citations go into speaker notes + a Sources slide. NotebookLM and Gamma do **not** document per-slide citations; Tome's slide product shut down 2025-04-30.
6. **Newsletter: one Celery beat "tick" entry + per-user schedule rows in SQLite + croniter (MIT, v6.2.4 of 2026-07-10, now community-maintained under pallets-eco) + a `(schedule_id, period_key)` UNIQUE sends table for idempotency.** Celery docs require a single beat instance; RedBeat (Apache-2.0) only if HA beat is needed; django-celery-beat (BSD-3-Clause) is Django-only; APScheduler 4 is still alpha (4.0.0a6, 2025-04-27). Email: Jinja2 + premailer (BSD-3-Clause); MJML not needed.
7. **TTS: provider-abstracted `tts_service`.** Official list prices: OpenAI tts-1 $15 / tts-1-hd $30 per 1M chars; gpt-4o-mini-tts $0.60/1M text-in tokens + $12/1M audio-out tokens (not deprecated on OpenAI's model page). Google Chirp 3: HD $30/1M chars and explicitly supports **hi-IN and en-IN** (53 locales). ElevenLabs Multilingual v2 lists Hindi; API rate $0.08/1K chars (= $80/1M). Best permissive local option for Hindi is **Chatterbox Multilingual V3 (MIT, 23 languages incl. Hindi + dedicated Hindi pack)**; Kokoro (Apache-2.0) grades its own Hindi voices C overall and needs GPL espeak-ng; Piper's successor repo is GPL-3.0; Coqui the company closed Jan 2024 (idiap fork MPL-2.0; XTTS weights non-commercial).
8. **Video: raw ffmpeg `filter_complex` pipeline** (already in-tree). moviepy (MIT) is alive but slow-moving (last release 2.2.1, 2025-05-21). Remotion is source-available with a company licence for 4+ people ($25/seat/mo; automation $0.01/render with $100/mo minimum) and needs Node + Chromium — reject. **Do not put YouTube footage in rendered output by default**: YouTube ToS (eff. 2023-12-15) forbids downloading except where YouTube provides it, and re-publishing clips is a copyright question where fair use is a defence, not a licence.
9. **Prior art worth copying:** NotebookLM's "Studio" panel (every output kind one click from the same grounded source set, citations deep-link to the passage); Perplexity Pages' thread→sectioned-article-with-per-section-sources (feature currently in flux as of 2026-07-16); Readwise's daily-review email of resurfaced highlights (the digest pattern); Obsidian Publish's per-note publish toggle + backlinks/graph ($8/site/mo annual); Scrivener's "Compile for" presets as a separate step.
10. **Cost:** an LLM cohesion pass over 10 × 5k-word reports (~262k input / ~78k output tokens across outline + per-chapter rewrite + front-matter passes) costs ≈ **$1.1 on gpt-5, $1.8 on gpt-5.4, $3.7 on gpt-5.5, $3.4 on Claude Opus 5.5, $4.2 on Opus 5, $1.7 on Sonnet 5.5, $0.22 on gpt-5-mini** at official list prices fetched 2026-10-19 (Claude figures include the ~30% tokenizer uplift Anthropic documents for 4.7+ models). Output tokens dominate; prompt-caching the shared outline/style prefix across the 10 chapter calls is the main lever.

---

## 1. Markdown/HTML → PDF in Python

| Candidate | Licence (SPDX) | Version / date | Renders our HTML? | Verdict |
|---|---|---|---|---|
| WeasyPrint | BSD-3-Clause (PyPI classifier says "BSD License"; the repo LICENSE is the 3-clause text) | 70.0, 2026-09-08; Python ≥3.10; Pango ≥1.44 | Yes, directly | **Recommended** |
| pandoc via pypandoc | pandoc GPL-2.0-or-later (with BSD-3-Clause exceptions); pypandoc MIT 1.17, 2026-03-14 | pandoc is not a PDF engine — it shells out to `--pdf-engine` (weasyprint, typst, wkhtmltopdf, LaTeX…) | Indirectly | Optional accelerator only |
| Typst (`typst` PyPI binding) | Apache-2.0 (both compiler and `messense/typst-py`) | 0.15.0, 2026-06-16; bundles the compiler via PyO3, no external binary | No — input is Typst markup, not HTML | Good typography, wrong input format |
| reportlab | BSD-3-Clause ("BSD License" classifier) | 5.0.1, 2026-08-20 | No — low-level canvas/Platypus API | Not an HTML renderer |
| xhtml2pdf | Apache-2.0 | 0.2.26, 2026-10-16; built on reportlab | Partial — CSS 2.1 subset, no flex/grid | Fragile with modern HTML |
| Playwright `page.pdf()` | Apache-2.0 | 1.64.0, 2026-10-13 | Yes, via headless Chromium | Fallback only |

**WeasyPrint details.**
- Windows install per the official docs: for library use, install MSYS2, run `pacman -S mingw-w64-ucrt-x86_64-pango` in the UCRT64 shell, then `pip install weasyprint`; if DLLs are not found set `WEASYPRINT_DLL_DIRECTORIES=C:\msys64\ucrt64\bin`. The docs no longer mention the GTK3 installer (maintainers moved to recommending MSYS2 because the GTK build lacked Fontconfig). A standalone `.exe` exists for CLI use only. Docs warn WeasyPrint "is regularly marked as malware" by antivirus vendors (false positives, issues #2081/#2092). Linux/Docker: `apt install libpango-1.0-0 libpangoft2-1.0-0`.
  - https://doc.courtbouillon.org/weasyprint/stable/first_steps.html
  - https://github.com/Kozea/WeasyPrint/issues/2105 (maintainer: use MSYS2, GTK build lacks Fontconfig)
  - https://pypi.org/project/weasyprint/
- CSS Paged Media Level 3: docs state "All the features of this draft are available" — `@page`, `:left/:right/:first/:blank`, page margin boxes, page-based counters, `size`/`bleed`/`marks`, named pages, `break-before/after/inside` (pages only, not columns), `orphans`/`widows`. GCPM: `string-set` named strings, `element()` running elements (except the `start` parameter), footnotes via `float: footnote`, `::footnote-marker`, `::footnote-call`. Bookmarks: `bookmark-level/label/state`, h1–h6 become the PDF outline by default; `<link rel=attachment>` embeds files. Not supported: min/max width/height on margin boxes, `footnote-display: compact`.
  - https://doc.courtbouillon.org/weasyprint/stable/api_reference.html
- A 2026 third-party benchmark of wkhtmltopdf alternatives reports WeasyPrint passing all 15 paged-media checks **[secondary]**: https://computingforgeeks.com/install-weasyprint-html-to-pdf/

**pandoc licence point, stated plainly.**
- pandoc's COPYRIGHT: "With the exceptions noted below, this code is released under the GPL, version 2 or later." Exceptions: `pandoc-types` modules BSD-3-Clause; `data/templates` dual GPL-2.0-or-later / BSD-3-Clause; dzslides JS/CSS WTFPL; embedded Lua under the Lua licence. https://hackage-content.haskell.org/package/pandoc-3.8/src/COPYRIGHT
- Calling the `pandoc` executable as a **separate process** from an MIT or AGPL application does not make the application a derivative work under the usual (FSF "mere aggregation"/separate-programs) reading; the GPL obligations attach to pandoc itself, which you must be able to satisfy if you *redistribute* the binary (e.g. by baking `pypandoc_binary` or the Debian package into an installer/Docker image: provide the pandoc source or a written offer). pypandoc's own page just says pandoc "is available under the GPL2 license" and does not address redistribution of the `pypandoc_binary` wheel. Community threads are split and there is no court precedent; the wasm-wrapping thread argues the stricter reading. Treat pandoc as **optional** (auto-detected on PATH, like Scrivener does) so the product never *requires* shipping a GPL binary.
  - https://pypi.org/project/pypandoc/
  - https://github.com/sergiocorreia/panflute/issues/92 (MIT wrapper, subprocess discussion)
  - https://github.com/haskell-wasm/pandoc-wasm/issues/13 (stricter view)
  - https://forum.eastgate.com/t/pandoc-working-group/8120?page=2
- GPL-2.0-or-later ↔ AGPL-3.0: "or later" lets pandoc be taken as GPL-3.0, which is compatible with AGPL-3.0 via GPL-3 §13 — relevant only if the code were *combined*, which a subprocess call is not.

**Typst**: `typst.compile(input, output=None, format="pdf"|"png"|"svg", ...)` returns bytes; input can be a path, bytes, or a dict of files. Excellent typography and speed, but you would need HTML→Typst (pandoc `-t typst` is the only mature route — back to the GPL binary). https://github.com/messense/typst-py · https://libraries.io/pypi/typst

**Playwright**: `page.pdf()` parameters confirmed in the Python docs — `format` (Letter…A6), `width/height/margin` (CSS units), `display_header_footer` + `header_template`/`footer_template` (script tags not evaluated), `print_background`, `prefer_css_page_size`, `scale` (0.1–2), `page_ranges`, `tagged` and `outline` (v1.42+). Chromium headless only (stated in third-party guides; the official page's note was outside the fetched window) **[secondary for the Chromium-only claim]**. Chromium has no `string-set`/running elements/footnotes, so book headers would have to be done through the header template, which cannot see page content. Each host also needs a ~150–300 MB Chromium download. https://playwright.dev/python/docs/api/class-page · https://www.checklyhq.com/learn/headless/generating-pdfs/ · https://pypi.org/project/playwright/

**Recommendation: WeasyPrint.** It consumes the HTML we already produce, needs no second runtime, is permissively licensed, and its paged-media support (running chapter headers, footnotes for citations, PDF outline, named front-matter pages) is exactly the book feature set. Keep Playwright as an already-optional fallback for anything that genuinely needs a browser engine (nothing in the current reports does).

## 2. EPUB generation

- **ebooklib** — PyPI metadata and classifier: "GNU Affero General Public License v3 or later (AGPLv3+)". v0.20, 2025-10-26. Arch packages it as AGPL-3.0-or-later. Importing it into Pratidhvani (a network-served app) triggers AGPL §13: every user interacting over the network must be offered the *complete corresponding source of the combined work*. Incompatible with keeping the product MIT or proprietary-SaaS. **Reject.**
  - https://pypi.org/project/EbookLib/ · https://archlinux.org/packages/extra/any/python-ebooklib
- **pandoc EPUB 3** — `-t epub3` (the `epub` writer defaults to v3; `epub2` available), `--epub-cover-image=FILE` (keep under 1000 px), `--epub-metadata=FILE` (Dublin Core XML; or YAML block), `--split-level=N` (`--epub-chapter-level` is a deprecated synonym), `--css` (falls back to `epub.css` in the user data dir, then built-ins). Input can be HTML directly (`-f html`). Same GPL-binary caveat as §1. https://pandoc.org/MANUAL.html
- **Hand-rolled zip** — EPUB 3 is a zip with an uncompressed `mimetype` entry first, `META-INF/container.xml`, a package document (`content.opf`: metadata, manifest, spine), `nav.xhtml`, XHTML chapter files and CSS. ~200–300 lines using `zipfile`, Jinja2 templates for the OPF/nav, and lxml (BSD-3-Clause) to serialise the existing HTML sections as XHTML (`method="xml"`). Validate with EPUBCheck (Java, BSD-3-Clause) in CI only, not at runtime. Zero new runtime dependencies, permissive licence, full control over citation links (`&t=` URLs survive as ordinary hyperlinks).

**Recommendation: hand-rolled EPUB 3 from the same Jinja2 book templates used for the PDF**, with pandoc as an auto-detected optional path. The report HTML is already semantic, which is most of the work; the EPUB and PDF then share one "book model" (title page, TOC, chapters = reports, endnotes = citations).

## 3. HTML → Markdown in Python

| Library | Licence (SPDX) | Version | Notes |
|---|---|---|---|
| markdownify | MIT (GitHub sidebar; PyPI page did not load in this session) | 1.2.3 (2026-06-30 per piwheels) / 1.2.2 (2025-11-16 per pepy) **[version secondary]** | BeautifulSoup-based; subclass `MarkdownConverter` to control headings, tables, nested lists, `<a>` handling |
| html2text | **GPL-3.0-or-later** (PyPI licence expression; description: "distributed under the GPLv3") | 2025.4.15 | Importing a GPL library into the server makes the combined work GPL on distribution (self-host tarball/Docker). Reject. |
| trafilatura | Apache-2.0 (≥1.8.0; earlier releases GPL-3.0-or-later) | 2.3.1, 2026-10-06 | `extract(html, output_format="markdown")` exists, but it is a boilerplate-removal extractor and will discard parts of a report it scores as non-content. Wrong tool for faithful conversion. |

- https://github.com/matthewwithanm/python-markdownify · https://www.piwheels.org/project/markdownify/
- https://pypi.org/project/html2text/
- https://pypi.org/project/trafilatura/ · https://github.com/adbar/trafilatura

**Recommendation: markdownify**, with a small `MarkdownConverter` subclass that (a) keeps `&t=` citation links intact, (b) renders `[VISUAL @ mm:ss …]` spans and blockquotes consistently, (c) emits ATX headings. Use it for the Markdown export of the book and for the `text/plain` alternative part of newsletters.

## 4. Static site generators and wiki publishing

**Generators**

| Tool | Licence (SPDX) | Runtime | Notes |
|---|---|---|---|
| Astro | MIT (GitHub) | Node | Component framework; overkill for a wiki export |
| Eleventy (11ty) | MIT (GitHub) | Node | Template-agnostic; still a Node build step |
| MkDocs | BSD-2-Clause (GitHub); 1.6.1 (2024-08-30), 2.0.dev6 pre-release (2026-09-15) | Python | Docs-nav model; backlinks/graph only via plugins **[plugin quality unverified]** |
| Pelican | AGPL-3.0-or-later (PyPI), 4.12.0 (2026-04-20) | Python | Importing = AGPL; subprocess use is fine but pointless |
| Zola | Code after v0.22 is EUPL-1.2; code before commit 3c9131d stays MIT (README) | Single Rust binary (~15 MB) | Copyleft (EUPL), but a separate binary; no Node |
| Quartz | MIT (GitHub, v5 branch) | Node | The de-facto self-hosted "digital garden" generator for Obsidian vaults |

- https://github.com/withastro/astro · https://github.com/11ty/eleventy · https://github.com/mkdocs/mkdocs · https://pypi.org/project/mkdocs/ · https://pypi.org/project/pelican/ · https://github.com/getzola/zola · https://github.com/jackyzha0/quartz

**Is bundling Node acceptable for a self-hosted Python app?** Technically yes: `nodejs-wheel-binaries` (MIT, v24.19.0 of 2026-08-19) installs Node via pip. But it adds a second runtime (~50–100 MB), a second package manager and a second supply chain to every self-host install, and it is why the Python ecosystem's answer is "ship prebuilt assets". The search found the pattern directly in django-adminlte (prebuilt bundle, no npm needed) and the counter-example swh-web (requires Node + yarn because bundles are not committed); my belief that Wagtail, NetBox, Paperless-ngx and Home Assistant all ship prebuilt frontends in their releases is general knowledge, **[unverified]** in this session. The project's own frontend already follows this pattern (Vite build output served by the backend).
- https://pypi.org/project/nodejs-wheel-binaries/ · https://django.adminlte.io/docs/assets/ · https://pypi.org/project/swh-web/

**How products publish personal wikis**
- **Obsidian Publish**: hosted; $8/site/month billed annually, $10 monthly (official pricing page). Renders a Markdown vault with per-note publish selection, backlinks, graph view, custom domain. https://obsidian.md/pricing
- **Quartz**: the open-source equivalent (MIT) — Markdown vault → static site with backlinks/graph, built with Node, hosted anywhere. https://github.com/jackyzha0/quartz
- **Notion Sites**: any page can be published to `*.notion.site` on all plans (free: one domain; paid: up to five); custom-domain add-on $10/month ($8 annual) per domain, up to 25 **[secondary mirrors of Notion help text]**. https://www.notion.com/id/help/notion-sites-availability-and-pricing · https://www.gend.co/blog/notion-pricing

**Recommendation: no SSG — an in-process Jinja2 "site" outputter.** Our inputs are DB rows and HTML, not a Markdown folder, so every SSG would first need a synthetic source tree and then a second runtime or a copyleft binary. A site is: `index.html`, one page per report, one page per document (with its knowledge report and `&t=` citations), tag/topic pages, backlinks computed from citations, a pre-built `search.json` and MiniSearch or Lunr.js (both MIT, vendored, no CDN needed) for client-side search, one CSS file reusing `theme.ts` tokens. Output is a zip (download) and optionally mounted under `/sites/{tenant}/…` by FastAPI `StaticFiles` behind the existing auth. If a theme ecosystem is ever wanted, MkDocs (BSD-2-Clause, importable, Python) is the Node-free upgrade path; Zola is the binary option.

## 5. PPTX generation

- **python-pptx**: MIT ("Copyright (c) 2013 Steve Canny"), v1.0.2 released 2024-08-07, no newer release found; mature and stable (text, bullets, tables, images, charts, speaker notes, layouts from a `.pptx` template). It cannot render slides to images — preview needs LibreOffice headless (MPL-2.0) or a client-side viewer. https://pypi.org/project/python-pptx/ · https://python-pptx.readthedocs.io/en/latest/user/intro.html
- Alternatives: Aspose.Slides (commercial), Apache POI (Java), Marp/`md2pptx` (Node / Python-on-python-pptx, **[not researched this session]**). None beats python-pptx for a Python backend.

**What AI deck products do**
- **NotebookLM Slide Deck** (Studio output; launched ~Nov 2025 per third parties; native "Export to PowerPoint" added 2026-02-18 per third parties; exported slides are flat images, 20-slide cap) **[secondary]**. Only chat answers carry inline citations that deep-link to source passages (official Google blog, 2024-06-06); I found **no** source documenting per-slide citations in Slide Decks or Video Overviews — the only "per-slide citation" material is a prompt-engineering workaround. https://blog.google/technology/ai/notebooklm-goes-global-support-for-websites-slides-fact-check/ · https://www.eesel.ai/blog/notebooklm-slide-deck-feature · https://codia.ai/blog/notebooklm-native-pptx-export-vs-noteslide · https://www.wps.com/topic/how-to-convert-notebooklm-slides-into-editable-ppt/
- **Gamma**: official pricing page returned 403; third parties (Sep 2026) list Free (400 one-time credits, 10 cards/prompt, Gamma badge), Plus $12/mo ($9 annual, 1,000 credits), Pro $25 ($18 annual, 4,000), Ultra $100 ($90 annual, 20,000, 75 cards/prompt); exports PPTX/PDF **[secondary, conflicting]**. No citation feature documented. https://www.eesel.ai/blog/gamma-pricing · https://www.chatslide.ai/articles/gamma-ai-review
- **Tome**: presentation product shut down 2025-04-30 (new sign-ups stopped, Pro cancelled, content deleted); founders pivoted to Lightfield (sales CRM) **[secondary; competitor-authored sources]**. https://www.chatslide.ai/articles/tome-ai-shut-down-what-happened · https://sacra.com/chat/h/86a38577-a643-49cd-95e5-8fb8429df303/

**Recommendation: python-pptx driven by an LLM-produced slide spec** (`{title, bullets[], notes, citations[{video_id, ts, quote}]}` per slide, one section per report heading, a closing Sources slide). Citations live in speaker notes with the `&t=` link and as a small footer reference on the slide — this is the differentiator none of the products above ship. Use a branded `.pptx` template from `docs/branding.md` tokens as the layout master.

## 6. Newsletter / digest scheduling

**Schedulers**

| Option | Licence (SPDX) | Fit |
|---|---|---|
| Celery beat (built-in) | BSD-3-Clause (Celery) | Docs: "You have to ensure only a single scheduler is running for a schedule at a time, otherwise you'd end up with duplicate tasks." Default `PersistentScheduler` stores last-run times in a local shelve file `celerybeat-schedule`. Custom scheduler via `--scheduler`. Nothing configured today. |
| django-celery-beat | BSD-3-Clause | Database scheduler, but Django ORM only — not usable with FastAPI/SQLAlchemy |
| celery-redbeat | Apache-2.0 | Redis-backed schedule with a lock, supports dynamic `RedBeatSchedulerEntry`; useful only if you need more than one beat process |
| celery-sqlalchemy-v2-scheduler | **[licence unverified]** | Exists on PyPI; small community |
| APScheduler | MIT (per distro packaging; official page didn't state) **[secondary]** | 3.11.x stable; 4.0 still pre-release (4.0.0a6, 2025-04-27) and "may change in a backwards incompatible fashion" — not for production |
| croniter | MIT; v6.2.4, 2026-07-10 | The 2025 "will be removed from PyPI on 2025-03-15" scare did **not** happen; the project now lives under `pallets-eco/croniter` ("part of the Pallets Community Ecosystem"), not archived. |
| cronsim | BSD-3-Clause **[secondary]** | Healthchecks' library; deliberately minimal (no seconds field) |

- https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html · https://github.com/sibson/redbeat · https://pypi.org/project/django_celery_beat/ · https://pypi.org/project/croniter/ · https://github.com/pallets-eco/croniter · https://pypi.org/project/cronsim · https://www.piwheels.org/project/apscheduler/ · https://apscheduler.readthedocs.io/en/master/migration.html

**Per-user schedules and idempotent sends (design, not a library):**
1. Table `newsletter_schedules(id, tenant_id, cron_expr, tz, scope, enabled, next_run_at, created_at)`; `cron_expr` validated with `croniter.is_valid`, `next_run_at` computed with `croniter(cron_expr, now_in_tz).get_next(datetime)` using `zoneinfo`.
2. Exactly one beat entry, a `newsletter_tick` task every minute (`crontab()`), that selects `enabled AND next_run_at <= now`, advances `next_run_at`, and enqueues `send_digest.delay(schedule_id, period_key)` where `period_key` = the ISO timestamp of the slot that fired (not the wall-clock time).
3. Table `newsletter_sends(schedule_id, period_key, status, message_id, sent_at, UNIQUE(schedule_id, period_key))`; `send_digest` does `INSERT … ON CONFLICT DO NOTHING` *before* rendering; if the insert did not happen, return. Set a deterministic `Message-ID` from `(schedule_id, period_key)` so any residual duplicate at least threads. Keep `acks_late=False` for this task (a lost worker means one missed digest, not a double send).
4. Add beat to `scripts/start.ps1` / `restart_services.ps1` as a separate process (`celery -A app.tasks.celery_app beat`), never inside the worker, to respect the single-instance rule.

**Email rendering**
- MJML is MIT but the reference compiler is Node; `mjml-python` (FelixSchwarz) is a pure-Python port (MIT) — "without requiring JavaScript, Node.js or Rust"; 0.x tracks MJML v4, the v5 port is unreleased. https://github.com/FelixSchwarz/mjml-python
- `premailer` — BSD-3-Clause (GitHub LICENSE); inlines CSS, resolves specificity, can fetch external sheets. https://github.com/peterbe/premailer
- `css_inline` — Rust-backed inliner **[licence unverified; PyPI page did not load]**.
- **Recommendation: Jinja2 HTML template (table layout, inline-friendly CSS) → premailer → `text/plain` alternative via markdownify → existing `email_service.py`.** MJML only if the design grows beyond what one table template handles.

## 7. TTS for narration

**Cloud list prices (fetched 2026-10-19)**

| Provider / model | Price | Hindi / Indian English |
|---|---|---|
| OpenAI `tts-1` | $15.00 per 1M characters | Languages "follow Whisper's list" — Hindi listed; voices "optimized for English" |
| OpenAI `tts-1-hd` | $30.00 per 1M characters | same |
| OpenAI `gpt-4o-mini-tts` | $0.60 per 1M text-input tokens + $12.00 per 1M audio-output tokens (≈ $0.015/min, OpenAI's own estimate **[secondary]**); steerable by prompt (accent, emotion, pace); official model page shows snapshots 2025-03-20 and 2025-12-15 (default) and **no deprecation notice**, despite some third-party calculators claiming one | same |
| ElevenLabs API | Free 10k chars; Starter $6 (75k); Creator $22 (275k); Pro $99 (1.238M); Scale $299 (3.738M); Business $990 (12.375M). Per model: v4 / v3 / Multilingual v2 $0.08 per 1K chars (= $80/1M); v4 Turbo / Flash $0.04 per 1K (= $40/1M) | Multilingual v2 (29 languages) and Flash v2.5 (32) explicitly list **Hindi** and Tamil; v3 "70+ languages" — Hindi not explicitly confirmed on the fetched page |
| Google Cloud TTS | Standard $4/1M chars; WaveNet $4/1M (cut from $16); Neural2 $16/1M; **Chirp 3: HD $30/1M**; Studio $160/1M; Gemini-TTS per token (official page confirmed via search index; the page itself truncated on fetch). Free tiers (4M Standard/WaveNet, 1M Neural2/Studio/Chirp 3) **[secondary]** | Chirp 3: HD officially lists **hi-IN and en-IN** among 53 locales |

- https://developers.openai.com/api/docs/pricing · https://developers.openai.com/api/docs/models/gpt-4o-mini-tts · https://developers.openai.com/api/docs/guides/text-to-speech
- https://elevenlabs.io/pricing/api · https://elevenlabs.io/docs/overview/capabilities/text-to-speech
- https://cloud.google.com/text-to-speech/pricing · https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd

**Local / open models**

| Model | Licence (SPDX) | Hindi | Status |
|---|---|---|---|
| Kokoro-82M (hexgrad) | Apache-2.0 weights (model card: "This is an Apache-licensed model"); inference code MIT | Yes, but the model card itself grades the four Hindi voices (hf_alpha, hf_beta, hm_omega, hm_psi) target B / overall C on 1–10 h of data, and warns non-English support "may be absent or thin due to weak G2P". Hindi G2P goes through misaki → **espeak-ng, which is GPL-3.0-or-later** (a runtime process dependency; mandatory for Hindi) | v1.0, 2025-01-27; 8 languages, 54 voices |
| Piper | Original `rhasspy/piper` (MIT) archived read-only Oct 2025 **[secondary]**; successor **`OHF-Voice/piper1-gpl` is GPL-3.0** (embeds espeak-ng) | `hi_IN` voice listed in VOICES.md; voices "intended for personal use and research", each with its own MODEL_CARD licence | Active (v1.8.0, 2026-09-04 **[secondary]**); Open Home Foundation recruiting maintainers |
| Coqui TTS | Company closed (announced 2024-01-03 **[secondary]**); `coqui-ai/TTS` unmaintained; `idiap/coqui-ai-TTS` fork is MPL-2.0, PyPI `coqui-tts` 0.27.x (Jan 2026) | XTTS-v2 supports Hindi, but the XTTS **weights** are under the Coqui Public Model License (non-commercial) **[secondary]** | Fork maintained, slower pace |
| Chatterbox (Resemble AI) | **MIT** (repo + README) | **Multilingual V3** (500M) covers 23 languages incl. `hi`; plus a dedicated **Hindi Single Language Pack** fine-tune; Turbo (350M) and Nano (110M) are English-only | Active; NVIDIA's hosted copy carries NVIDIA's own agreement, Resemble's weights are MIT |
| Dia (Nari Labs) | Apache-2.0 | **English only** ("only supports English generation at the moment"); Dia2 released, details not on the page | 1.6B params |

- https://huggingface.co/hexgrad/Kokoro-82M · https://replicate.com/codingayam/kokoro-82m-complete/readme (Hindi grades) · https://github.com/espeak-ng/espeak-ng
- https://github.com/OHF-Voice/piper1-gpl · https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md · https://www.cekura.ai/discover/piper-tts
- https://github.com/idiap/coqui-ai-TTS · https://aiwiki.ai/wiki/xtts
- https://github.com/resemble-ai/chatterbox · https://github.com/nari-labs/dia

**Which handles Hindi / Indian English well?** Cloud: Google Chirp 3: HD (explicit hi-IN *and* en-IN voices) and ElevenLabs Multilingual v2 (explicit Hindi). OpenAI works for Hindi but its voices are English-optimised — fine for the English-output default (D-066), weaker for Hindi narration. Local with a permissive licence: Chatterbox Multilingual V3 / Hindi pack (MIT). Kokoro's Hindi is self-rated C and drags in GPL espeak-ng; Piper is GPL. Nobody publishes a Hindi quality benchmark — a listening test on our own corpus is required, and **romanised Hinglish** (the known hard case) is untested by every model card I read.

**Worked cost, 10-minute narration (~1,500 words ≈ 9,000 chars):** OpenAI tts-1 $0.14, tts-1-hd $0.27, gpt-4o-mini-tts ≈ $0.15; Google Neural2 $0.14, Chirp 3 HD $0.27; ElevenLabs Multilingual v2 $0.72 at the API rate.

## 8. Video assembly

- **moviepy**: MIT; latest 2.2.1 (2025-05-21); v2.0 (Nov 2024) broke the v1 API and v1 is unmaintained; GitHub release list ends at 2.2.1 and a snapshot showed last commit 2025-02-06 — alive but slow. It is an ffmpeg wrapper that pushes frames through numpy, so long 1080×1920 renders are slow. https://pypi.org/project/moviepy/ · https://github.com/Zulko/moviepy/releases
- **Raw ffmpeg**: the concat *demuxer* stream-copies and needs identical codec/resolution/fps across inputs; the concat *filter* inside `filter_complex` re-encodes and allows per-clip `scale`/`pad`/`crop`/`fps` normalisation and `drawtext`/`subtitles` burn-in before the join. Since 9:16 normalisation and captions force a re-encode anyway, the filter route is the natural one. `frame_service.py` already shells out to ffmpeg. ffmpeg's licence is LGPL-2.1-or-later or GPL-2.0-or-later depending on build flags (libx264 → GPL) — already accepted by the project. https://cloudinary.com/blog/questions/how-can-i-concatenate-videos-with-ffmpeg · https://lists.ffmpeg.org/pipermail/ffmpeg-user/2020-April/048030.html
- **Remotion**: source-available, not OSI. Free for "an individual", "a for-profit organization with up to 3 employees", and non-profits; a Company License is required otherwise ("companies of 4+ people"): Creators $25/mo per seat; Automators $0.01 per render with a $100/month minimum; Enterprise from $500/mo; "In Remotion 5.0, the license will slightly change." React + Node + Chromium rendering. Reject for this stack. https://github.com/remotion-dev/remotion/blob/main/LICENSE.md · https://www.remotion.pro/license

**Legal note, stated plainly.** YouTube Terms of Service (effective 2023-12-15), "Permissions and Restrictions", prohibit users from "access[ing], reproduc[ing], download[ing], distribut[ing], transmit[ting], broadcast[ing], display[ing], sell[ing], licens[ing], alter[ing], modify[ing] or otherwise us[ing] any part of the Service or any Content except (a) as expressly authorized by the Service; or (b) with prior written permission from YouTube and, if applicable, the respective rights holders", and separately prohibit automated access ("robots, botnets or scrapers") outside robots.txt-compliant search engines. So:
1. Fetching video with yt-dlp (which R1 frame capture already does) is a **contract breach** against YouTube regardless of copyright; the exposure is account/IP action (the D-051 blocks are the practical symptom).
2. **Re-publishing** clips in a reel is a separate **copyright** question. Fair use (US) / fair dealing (elsewhere) is a defence argued case-by-case on purpose, nature, amount and market effect; short clips with commentary fare better, but public distribution and any commercial framing push the other way, and the burden is on the person claiming it.
3. A product that automates this for many users is at the risky end: it faces DMCA takedowns on the outputs and secondary-liability arguments, not just the individual user's risk.
Mitigations: default to **no third-party footage** in rendered output — build the reel from TTS narration over app-generated title/quote/stat cards, the user's own uploads, or licensed stock (Pexels/Pixabay APIs have their own terms); show the `&t=` citation on screen as a card rather than the clip; keep the app's own extracted frames (R1) for private analysis only; make B-roll from YouTube an explicit per-render opt-in with the risk statement in the UI; never host rendered reels publicly from Pratidhvani.
- https://www.youtube.com/t/terms · https://www.techsmith.com/blog/download-youtube-videos/ · https://community.adobe.com/t5/premiere-pro-discussions/how-is-everyone-safely-downloading-video-from-youtube-to-edit-in-premiere/m-p/12631917

**Vertical 9:16 conventions** (vendor blogs; platform UIs shift often — **[secondary]**): master at 1080×1920, 30 fps (60 acceptable), H.264 High, `yuv420p`, AAC 128–192 kbps, `-movflags +faststart`. Keep titles/captions inside a central band: roughly the top 12–15% and bottom 20–25% are covered by platform chrome and the right ~15% by the action rail; burn captions around 60–70% of frame height, never in the bottom 10%. ffmpeg: fill with `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920`, or letterbox with `scale=1080:-2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2`; captions via `subtitles=` (ASS/SRT) or `drawtext`. https://kineclip.com/blog/vertical-video-dimensions-and-safe-zones-2026/ · https://vidpros.com/vertical-video-safe-zone/ · https://postmypost.io/resources/vertical-video-2026-safe-zones-text-and-editing-how-to-create-content-that-doesn-t-cut-through-algorithms/

## 9. Prior art

**NotebookLM (Google; one source says renamed "Gemini Notebook" July 2026 [unverified]).** A notebook is a set of uploaded/linked sources; a "Studio" panel turns the same grounded set into Audio Overview (two-host podcast), Video Overview, Cinematic Video Overview (Ultra tiers, launched 2026-03-04 per third parties), Mind Map, Reports, Flashcards, Quiz, Infographic, Slide Deck (PPTX export since Feb 2026, slides as images) and Data Table. Chat answers carry inline citations that jump to the source passage (official, 2024-06-06). Pricing is bundled into Google AI plans; third parties list Plus $4.99, Pro $19.99, Ultra $99.99/$199.99 with per-day output caps (Audio Overviews 3/6/20/100/200 per day by tier) — figures conflict across sources. Worth copying: one "Studio" surface where every output kind is a single click on the same source set; strict grounding; citation deep-links (our `&t=` links already do this — keep them in *every* output kind, which NotebookLM's slides/video do not). https://blog.google/technology/ai/notebooklm-goes-global-support-for-websites-slides-fact-check/ · https://felloai.com/notebooklm-pricing/ · https://notebooklm-guide.com/notebooklm-system-limits-benchmarks/

**Perplexity Pages (launched 2024-05-30).** Converts a research thread into a sectioned article with per-section sources at a public `perplexity.ai/page/...` URL; free. As of the help-center update of 2026-07-16 the standalone "Create page" button is "temporarily retired" and "Convert to Page" is to return with enhanced capabilities — the feature is in flux. Worth copying: thread → outline → editable sections each carrying its own citations, with a review step before publishing. https://venturebeat.com/ai/perplexity-goes-beyond-ai-search-launches-publishing-platform-pages · https://gptprompts.ai/perplexity-pages-guide · https://tomsguide.com/ai/i-tried-perplexitys-new-pages-feature-wikipedia-should-be-worried

**Google Docs / Gemini.** Gemini in Docs/Slides drafts text and slides from Drive content inside the editor, bundled into Google AI Pro / Workspace. **Not researched in depth this session** (search budget); worth copying the principle: generate *inside the editing surface* and let the user edit before export rather than emitting a locked file.

**Readwise / Reader.** Full plan $9.99/month billed annually ($119.88/yr) or $12.99 monthly; Lite $5.59/month annual excludes Reader; 30-day trial, no free tier (official pricing page). Reader = read-later + highlights + "Ghostreader" LLM summaries; Readwise's signature is the daily review email that resurfaces your own highlights on a spaced schedule. Worth copying: the scheduled digest is *your own library re-surfaced*, not new content — exactly what a Pratidhvani newsletter over the user's Q&A history and new ingests should be. https://readwise.io/pricing

**Obsidian Publish.** $8/site/month annual, $10 monthly (official). Hosted rendering of a Markdown vault with per-note publish toggles, backlinks, graph view, custom domain; Quartz (MIT, Node) is the self-host equivalent. Worth copying: per-page publish flag with private default, backlinks and a graph derived from citations, and a stable URL per note. https://obsidian.md/pricing · https://github.com/jackyzha0/quartz

**Scrivener / Pandoc workflows.** Scrivener 3 is $59.99 per platform (macOS or Windows), $95.98 bundle, iOS $23.99 **[secondary]**. "Compile" is a separate step with presets: ePub 3, Kindle, DOCX (incl. Vellum-ready), PDF (incl. PDF/X-1a), MultiMarkdown, and Pandoc targets that appear **only if pandoc is installed** — Literature & Latte explicitly chose not to bundle pandoc because it is "a bit too large". Worth copying: the compile-step model (binder hierarchy → chapters, front/back matter, format presets, metadata) and the "pandoc optional, auto-detected" precedent for our own pandoc handling. https://literatureandlatte.com/downloads/3_0_3.html · https://forum.literatureandlatte.com/t/multimarkdown-vs-pandoc-why-multimarkdown-is-the-preferred-for-latex-compilation/40267 · https://www.casrai.org/guides/scrivener-pricing

## 10. Cost implications of an LLM cohesion pass

**Official list prices, per 1M tokens, fetched 2026-10-19**

| Model | Input | Output | Cache read |
|---|---|---|---|
| OpenAI gpt-5 | $1.25 | $10.00 | — |
| OpenAI gpt-5.4 (<272K) | $2.50 | $15.00 | $0.25 |
| OpenAI gpt-5.5 (<272K) | $5.00 | $30.00 | $0.50 |
| OpenAI gpt-5.4-mini / gpt-5-mini | $0.75 / $0.25 | $4.50 / $2.00 | — |
| Anthropic Claude Opus 5.5 | $4 | $20 | $0.20 |
| Anthropic Claude Opus 5 / 4.8 / 4.7 / 4.6 / 4.5 | $5 | $25 | $0.50 |
| Anthropic Claude Sonnet 5.5 / Sonnet 5 | $2 | $10 | $0.10 / $0.20 |
| Anthropic Claude Haiku 5.5 (≤100K prompt) | $0.10 | $0.50 | $0.01 |
| Anthropic Claude Fable 5.1 | $10 | $50 | $0.25 |

Anthropic's page notes that Claude 4.7+ models use a tokenizer producing "approximately 30% more tokens for the same text". OpenAI's page also lists gpt-6-family models (gpt-6-astra $10/$50, gpt-6.1-sol $2/$10, gpt-6-luna $0.10/$0.50) — recorded here for completeness, not used below.
- https://developers.openai.com/api/docs/pricing · https://platform.claude.com/docs/en/about-claude/pricing

**Token model for "10 reports × 5,000 words"** (≈50k words ≈ 67k tokens at 1.33 tokens/word; ×1.3 for Claude 4.7+):
- Outline pass: read all ten (67k in) → book outline + style sheet (3k out).
- Chapter pass ×10: report (6.7k) + outline/style prefix (5k) in, rewritten chapter (7k) out → 117k in, 70k out.
- Front/back matter + cross-reference pass: 75k in, 5k out.
- Total ≈ **262k input, 78k output** (Claude: ≈341k / 101k).

**Per-book cost at list price**

| Model | Cost |
|---|---|
| gpt-5-mini | $0.22 |
| gpt-5 | $1.11 |
| Sonnet 5.5 | $1.69 |
| gpt-5.4 | $1.83 |
| Opus 5.5 | $3.39 |
| gpt-5.5 | $3.65 |
| Opus 5 | $4.23 |
| Fable 5.1 | $8.46 |

Output tokens are 60–70% of the bill. Putting the shared outline + style prefix first in each chapter call and using prompt caching cuts the input side by roughly a third; a second full-read QA pass adds ~$0.1–0.4 on gpt-5-class models. For scale: deck (~10k in / 3k out) ≈ $0.05, newsletter (~20k in / 1.5k out) ≈ $0.04, 10-minute video script (~15k in / 2k out) ≈ $0.04 on gpt-5; TTS adds $0.14–0.72 per 10 minutes (see §7).

---

## Recommendations

- **Book (PDF)** — WeasyPrint, BSD-3-Clause: consumes our HTML directly, pure Python + Pango, full Paged Media/GCPM (running headers, footnotes, PDF outline); Playwright (Apache-2.0, already optional) only as a fallback.
- **Book (EPUB)** — hand-rolled EPUB 3 with `zipfile` + lxml (BSD-3-Clause) + Jinja2: zero new deps, permissive; ebooklib rejected (AGPL-3.0-or-later); pandoc (GPL-2.0-or-later) auto-detected and optional, never required or bundled.
- **Book (Markdown export)** — markdownify, MIT: faithful structural conversion; html2text rejected (GPL-3.0-or-later); trafilatura rejected (extractor, drops content).
- **Site** — in-process Jinja2 static export + vendored MiniSearch/Lunr (MIT) search index, served by FastAPI `StaticFiles` or zipped: no Node, no copyleft binary, inputs are already DB rows + HTML; MkDocs (BSD-2-Clause, Python) is the upgrade path if a theme ecosystem is wanted.
- **Slides** — python-pptx, MIT: stable since 2013, template-driven; citations in speaker notes + Sources slide, which no AI deck product ships.
- **Newsletter** — Celery beat single `tick` entry + SQLite schedule rows + croniter (MIT) + UNIQUE `(schedule_id, period_key)` sends table; Jinja2 + premailer (BSD-3-Clause) HTML, markdownify text part, existing `email_service.py`; RedBeat (Apache-2.0) only if HA beat is needed.
- **Video / reel** — ffmpeg `filter_complex` (already in-tree) + provider-abstracted `tts_service` (default OpenAI gpt-4o-mini-tts; Google Chirp 3: HD for hi-IN/en-IN; Chatterbox MIT as the local option); no YouTube footage in output by default; moviepy unnecessary, Remotion rejected (company licence, Node + Chromium).

## Risks and open questions

1. **Copyleft traps to keep out of `requirements.txt`:** ebooklib (AGPL-3.0-or-later), html2text (GPL-3.0-or-later), Pelican (AGPL-3.0-or-later), piper1-gpl (GPL-3.0), espeak-ng (GPL-3.0-or-later; required for Kokoro Hindi and embedded in Piper). pandoc and Zola are acceptable only as separate, optional binaries; redistributing pandoc inside an installer/Docker image creates GPL source-offer obligations for pandoc itself.
2. **Windows developer experience:** WeasyPrint needs MSYS2 Pango and is a known antivirus false positive; CI/Docker on Linux is simple (`apt install libpango-1.0-0 libpangoft2-1.0-0`). Decide whether `start.ps1` should check for `WEASYPRINT_DLL_DIRECTORIES`.
3. **YouTube B-roll is a product decision, not a library choice:** downloading breaches the ToS (eff. 2023-12-15); re-publishing is a copyright exposure with fair use as a defence only. The recommendation is "no third-party footage by default"; if the roadmap insists on clip-stitched B-roll, record the risk in `docs/decisions.md` and gate it per render.
4. **Hindi / Hinglish narration quality is unmeasured:** no public Hindi benchmark exists for any TTS listed; Kokoro self-grades C; romanised Hinglish is untested everywhere. A listening test on our corpus (Devanagari and romanised) is required before choosing the default voice for non-English narration.
5. **gpt-4o-mini-tts status:** OpenAI's model page shows no deprecation and a 2025-12-15 snapshot, but at least one third-party calculator claims it is deprecated. Re-check the model page when implementing; the `tts_service` abstraction should make the model a config value.
6. **Scheduler constraints:** Celery beat must run as exactly one process (add to the launcher scripts); APScheduler 4 is still alpha; croniter is community-maintained under pallets-eco (bus-factor risk, but MIT and current as of 2026-07-10).
7. **Third-party pricing is inconsistent:** NotebookLM tiers/limits, Gamma plans (official page 403), Google TTS free allowances, Remotion's "5.0 licence change", markdownify 1.2.3's release, cronsim/css_inline licences, and the Tome shutdown narrative all rest on secondary sources — marked above. Anthropic, OpenAI, ElevenLabs, Readwise, Obsidian and the YouTube ToS were read from primary pages.
8. **Site search without Node:** a pre-built JSON index with MiniSearch/Lunr is fine for hundreds of pages; for thousands, Pagefind (MIT, Rust binary, no Node) is the next step and would be the first binary the site outputter depends on.
9. **EPUB validation and PPTX preview** need Java (EPUBCheck) and LibreOffice respectively — CI-only / optional, not runtime dependencies.
10. **Cost model assumptions:** 1.33 tokens/word and the three-pass design are estimates; actual report HTML carries markup overhead (strip to Markdown via markdownify *before* the cohesion pass to avoid paying for tags). Token counts should be measured on real reports before committing the per-use-case registry entries.
11. **WebSearch budget was exhausted** near the end of this session; the Google Docs/Gemini prior-art paragraph and the "Wagtail/NetBox ship prebuilt assets" claim are the two places where I did not reach a primary source.
