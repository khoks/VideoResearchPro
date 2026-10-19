# M8 — Reading room, the report as a native reading view: plan

**Board:** [E-8.8](../initiatives.md#e-88--reading-room--the-report-as-a-native-reading-view-m8) · **Roadmap:** [M8](../feature-roadmap.md#m8--reading-room-reader-for-reports-) · **Design:** [ui-design.md §2.3](../ui-design.md) · **Research date:** 2026-10-19 · **Status:** recommendation.

## Problem

Reports are the longest piece of content the app produces and they are read inside an `<iframe>` modal with the report's own embedded stylesheet, no outline, no progress, no citation affordance beyond a bare link, and a JWT in the iframe URL. The design doc already specifies the reading room (measure, drop cap, sticky outline, hover citations, progress, print). The roadmap sketched "a native MDX-rendered reading view" and an optional Markdown source.

## Verified current state (2026-10-18)

- Reports are LLM-written **semantic HTML section bodies** (`agents/prompts/report_prompts.py` instructs `h2`, `h3`, `p`, `ul`, `table` with CSS classes), wrapped by `utils/html_builder.py` with a `<style>` block and a statistics grid, written to one file at `jobs.report_path`. **There is no Markdown source**; MDX is not an option without a lossy conversion.
- `routers/qa.py` `get_report` serves the HTML with `get_user_from_query_or_header`: the `?token=` fallback exists only because an iframe cannot send an Authorization header. `JobDetailPage.ReportModal` builds that URL and also opens it in a new tab.
- Citations inside the HTML are `<a href="…&t=123">` anchors; S-1.14.9 fixed the dead-link class and `_strip_broken_links` unwraps non-URL anchors.
- Knowledge reports are Markdown rendered with `react-markdown` (`VideoKnowledgePage` drawer).
- `theme.ts` has `measure.reading = '75ch'` and typography tokens; `ui-design.md` §2.3 and §2.4 specify the reading view and its mobile behaviour.
- R1 frames (`visual_frames`) exist but have no serving route yet (S-1.18.2).

## Chosen approach

**Keep reports as HTML; render them natively in React after sanitising.**

- **Fetch** the report body through the authenticated API (Authorization header; `{title, html, statistics}`), so no token ever appears in a URL. Once the iframe is gone, retire `get_user_from_query_or_header` on that route: it is a log-leak surface.
- **Pipeline:** `DOMPurify.sanitize(html, {FORBID_TAGS: ['style', 'script'], ADD_ATTR: ['target']})` (DOMPurify 3.4.17, dual MPL-2.0 / Apache-2.0, elect Apache-2.0 and record it; about 12 kB gzipped; zero dependencies) → `html-react-parser` (MIT, about 11 kB; explicitly *not* a sanitiser, so it is always fed DOMPurify output) with a `replace` hook that turns `&t=` anchors into `<CitationLink>`, assigns heading ids and collects the outline, and wraps `<table>` in a scroll container (WCAG 1.4.10). About 22 kB gzipped in the core bundle.
- **`ReaderShell`** layout: 65–75ch measure, body line-height about 1.6; drop cap via `::first-letter` float with `initial-letter` under `@supports` (Firefox still lacks `initial-letter` through 161; Safari needs the `-webkit-` prefix); `text-wrap: pretty` on body as enhancement (Chrome 117, Safari 26, not Firefox) and `balance` on headings; `hanging-punctuation` set (Safari-only, harmless elsewhere); a sticky `<nav aria-label="Outline">` driven by one `IntersectionObserver` over `h2, h3` with `aria-current`; a reading-progress bar from `scrollTop / (scrollHeight − clientHeight)` throttled with `requestAnimationFrame`, `aria-hidden`; `prefers-reduced-motion` disables smooth scrolling and transitions; the sticky chrome must not cover the focused element (WCAG 2.2 SC 2.4.11).
- **Citation cards** (S-8.8.2): chips with hover and focus cards using the Popover API (Baseline 2025) positioned with `getBoundingClientRect` (CSS anchor positioning is still partial everywhere), showing title, channel, timestamp and quote where available, polymorphic by `source_type`; a numbered endnote list for print and screen readers; a hook for R1 stills once S-1.18.2 serves them.
- **Print**: `@media print` hides outline, progress and chrome; `a[href]::after { content: " (" attr(href) ")" }` or the endnote list for citations; `break-inside: avoid` on cards and blockquotes; `break-before: page` on `h2`; `@page { margin: 2cm }`.
- **Route** `/reports/:jobId`; a "Read" button on `JobDetailPage`; the modal stays as a quick peek. The same shell renders knowledge artifacts (`react-markdown` with `remark-gfm`, `rehype-slug`, all MIT) and later public shares (M11) and Author outputs (E-6.1).

## Alternatives rejected

| Option | Why not |
|---|---|
| Convert reports to Markdown and render with `react-markdown` (the roadmap's MDX idea) | Lossy (tables, nested lists, figure and aside markup the LLM writes), needs a server converter and a migration of stored reports, and still needs sanitising of raw HTML blocks. The Markdown source E-6.1 adds is for export, not for display. |
| `sanitize-html` | 50 kB gzipped with htmlparser2 and postcss; DOMPurify is a quarter of that. |
| A rehype pipeline (`rehype-parse` → `rehype-sanitize` → `rehype-react`) | Reasonable second choice sharing the `react-markdown` ecosystem; similar size once `parse5` is counted; chosen against because DOMPurify is the better-audited sanitiser. |
| Keep the iframe and style it | Cannot share typography, outline or citation components; keeps the token in the URL. |
| Server-side section parsing into JSON | Unnecessary once the client parses; M11's public route can return the same `{title, html}` shape. |

## Schema deltas

None.

## API deltas

`GET /api/v1/jobs/{id}/report` keeps serving HTML for "Open in new tab"; a new `GET /api/v1/jobs/{id}/report/body` returns `{title, html, statistics}` under header auth only. After the modal is replaced, remove the query-token fallback.

## Modules touched

`routers/qa.py` (body route, later the fallback removal), `dependencies.py` (`get_user_from_query_or_header` retirement), `frontend/src/pages/ReportReaderPage.tsx` and `components/reader/{ReaderShell,Outline,ProgressBar,CitationCard}.tsx` (new), `components/citation/CitationLink.tsx`, `JobDetailPage.tsx`, `VideoKnowledgePage.tsx` (shell reuse), `routes/index.tsx`, `index.css` (print and `@supports` rules; a reader needs a few real CSS rules), `theme.ts`, `package.json` (`dompurify`, `html-react-parser`, `remark-gfm`, `rehype-slug`).

## Risks

- **Sanitiser configuration**: DOMPurify keeps `<style>` by default (verify against the current allow-list); forbid it so the reader's typography wins, and forbid event handlers and `javascript:` URLs (default).
- **Firefox**: no `initial-letter`, no `text-wrap: pretty`; the fallbacks must be the design, not the exception; Playwright screenshots will differ per browser.
- **Old reports**: every stored report must render; test on three real files from the data directory.
- **Bundle**: 22 kB in the core bundle is acceptable against the 170 kB critical-path budget.

## Test strategy

- Unit (frontend): sanitiser rejects `<script>`, `onerror`, `javascript:`; the `replace` hook produces one outline entry per heading and one `CitationLink` per `&t=` anchor; a three-report fixture set renders without errors.
- Router: body route requires header auth; the query-token path removed in the follow-up asserts 401.
- Accessibility: keyboard reaches every citation; `aria-current` moves with scroll (Playwright); reduced-motion respected.
- Visual: Playwright screenshots of the reader at desktop and 640px for the M12 baseline.

## First PR (S-8.8.1)

The body route, the sanitise-and-parse pipeline, `ReaderShell` with measure, drop cap, outline and progress, the `/reports/:jobId` route and the "Read" button, plus tests. Citation cards and print are S-8.8.2; the shared shell for knowledge and outputs is S-8.8.3.

## Open questions

1. Retire the `?token=` report route in the same PR or one PR later (recommended: later, after the modal's "Open in new tab" moves to the reader)?
2. Should the quick-peek modal survive at all once the reader exists?

## Sources (fetched 2026-10-19)

npm and Bundlephobia for `dompurify`, `html-react-parser`, `sanitize-html`, `rehype-sanitize`, `rehype-react`, `react-markdown`, `remark-gfm`, `rehype-slug`, `rehype-autolink-headings`; DOMPurify LICENSE; caniuse and MDN for `initial-letter`, `hanging-punctuation`, `text-wrap`, Popover API, CSS anchor positioning, `@page`, `break-inside`, `prefers-reduced-motion`; WebKit features in Safari 26.0; Practical Typography on line length; W3C WCAG 2.2 "what's new". Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
