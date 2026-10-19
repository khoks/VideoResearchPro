# M12 — Mobile reading mode: plan

**Board:** [E-8.12](../initiatives.md#e-812--mobile-reading-mode-m12) · **Roadmap:** [M12](../feature-roadmap.md#m12--mobile-reading-mode-) · **Design:** [ui-design.md §2.4](../ui-design.md) · **Research date:** 2026-10-19 · **Status:** recommendation.

## Problem

The layout collapses to a single column under 640px and the sidebar becomes a hamburger under 960px, and that is all. Reading a report, following a Q&A thread or opening a knowledge artifact on a phone means small type, tiny citation links, a composer that hides behind the keyboard and no safe-area handling. The roadmap scopes this to the *reading* experience, not a general mobile redesign.

## Verified current state (2026-10-18)

- `frontend/src/index.css` holds two media rules: sidebar off and mobile bar on under 960px; `.form-row` stacks under 640px. `theme.ts` defines breakpoints 640 / 960 / 1200 and `measure.reading = '75ch'`.
- Reports render in an iframe modal (M8 replaces it); Q&A composers are inline textareas in `JobDetailPage` and `LibraryQAPage`; knowledge artifacts render through `react-markdown` in a drawer.
- No viewport meta customisation beyond the default; no web-app manifest; no service worker; no device-emulated tests (Playwright is available to the project through the article-extraction optional dependency and the test tooling).

## Chosen approach

Almost entirely CSS with full browser support, applied to the M8 reader and the two Q&A pages:

- **Targets**: ≥ 24 × 24 CSS px everywhere (WCAG 2.2 SC 2.5.8, AA) and ≥ 44 px on primary controls (Apple HIG; Android asks 48 dp with 8 dp spacing); inline citation chips inside a sentence are exempt, but the "open at timestamp" buttons in their cards are not; hit areas via padding, not icon size.
- **Viewport and keyboard**: `height: 100dvh` for the reader shell and `svh` for the docked composer view (supported since Chrome 108, Firefox 101, Safari 15.4); `viewport-fit=cover` with `padding-bottom: env(safe-area-inset-bottom)` on the composer; **inputs at 16 px** so iOS does not zoom on focus, and never `maximum-scale=1` (ignored by iOS 10+ by default and a WCAG 1.4.4 failure); the bottom-docked composer pinned above the keyboard with the VisualViewport API (`resize` and `scroll` events, `requestAnimationFrame`-throttled translate), the ChatGPT and Claude mobile pattern; `overscroll-behavior: contain` on the thread so scrolling does not chain into the page.
- **Typography**: fluid `clamp()` type scale tokens in `theme.ts`, `max-width: 65ch`, `text-wrap: pretty` as enhancement, `balance` on headings; 320 px reflow without two-dimensional scrolling (WCAG 1.4.10; tables in their own scroll container); line-height in unitless values (1.4.12).
- **Reader on phones** (per `ui-design.md` §2.4): drop the outline under 960px, keep drop cap and citations; a compact bottom toolbar (outline sheet, font size, theme).
- **Gestures**: no edge-anchored horizontal gestures (iOS Safari's edge swipe owns history); the hamburger button, not a swipe, opens the sidebar; the M9 graph pan must not start within about 20 px of the edge.
- **Web-app manifest** (S-8.12.2): `manifest.webmanifest` with `display: standalone`, icons and `theme_color`, about 30 lines; Safari 26.0 opens any Home-Screen site as a web app with or without one. A service worker is **deferred**: it complicates JWT-gated fetches and report invalidation, and offline reading is not a requirement. The icon depends on the logo work still open in the rebrand table.
- **Tests**: Playwright projects with `devices['iPhone 13']` (WebKit), `devices['Pixel 7']` (Chromium) and a 320 px custom viewport, light and dark, screenshotting the reader, the job Q&A thread and a knowledge artifact; checked in as the baseline.

## Alternatives rejected

| Option | Why not |
|---|---|
| A separate mobile layout or app shell | Out of scope; the roadmap wants reading refinements. |
| `maximum-scale=1` / `user-scalable=no` to stop zoom | Ignored by iOS and an accessibility failure; 16 px inputs solve it. |
| A service worker now | Cost without a stated need; JWT and invalidation complications. |
| Fixed `100vh` layouts | Toolbars make `vh` wrong on phones; `dvh` / `svh` exist for this. |
| Swipe-to-open sidebar | Conflicts with the back gesture. |

## Schema deltas

None.

## API deltas

None.

## Modules touched

`frontend/index.html` (viewport meta, manifest link), `frontend/public/manifest.webmanifest` and icons (new), `theme.ts` (fluid tokens), `index.css` (a few real responsive rules), `components/reader/*` (M8), `JobDetailPage.tsx`, `LibraryQAPage.tsx`, `VideoKnowledgePage.tsx`, `components/qa/Composer.tsx` (extract and dock), `frontend/playwright.config.ts` (device projects, new), `frontend/tests/mobile.spec.ts` (new).

## Risks

- **Screenshot drift** across engines (`text-wrap: pretty` absent in Firefox, drop-cap fallback differences); keep baselines per project and tolerate small diffs.
- **Emulation is not a device**: no real keyboard, no Safari chrome, host CPU; a manual pass on one real phone before calling it done.
- **Back-gesture behaviour in standalone mode** is unverified; avoid relying on it.

## Test strategy

Device-emulated Playwright screenshots (three pages × three profiles × two colour schemes); an assertion that no horizontal scroll exists at 320 px; target-size assertions on primary controls via bounding boxes; a VisualViewport simulation for the composer (resize the viewport and assert the composer stays visible); type-check.

## First PR (S-8.12.1)

The viewport meta, fluid tokens, target sizes, safe areas, `dvh`, 16 px inputs, the docked composer with VisualViewport pinning, and the Playwright device projects with baselines for the three pages. The manifest is S-8.12.2 and can ship the same day.

## Open questions

1. Is a real-device pass (one iPhone, one Android) part of acceptance, or are emulated screenshots enough for now?
2. Which icon, given the logo is still Vite's default bolt?

## Sources (fetched 2026-10-19)

W3C WCAG 2.2 SC 2.5.8 and 1.4.10; Apple Design Tips (44 pt); Google Android accessibility help (48 dp); caniuse for viewport-unit variants and `env()`; MDN viewport meta, VisualViewport, `overscroll-behavior`; West Wind on iOS textbox auto-zoom; WebKit features in Safari 26.0 (Home-Screen web apps); vendor pages on iOS PWA limitations; Playwright emulation docs; web.dev performance budgets; Vite build options. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
