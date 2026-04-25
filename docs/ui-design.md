# Pratidhvani — UI Design System

**Status:** approved (2026-04-24). This is the **single source of truth** for the visual language: design tokens, primitives, layout, motion, accessibility, dark mode. Brand identity (logo, name, tagline, voice) lives in [branding.md](branding.md). Page-level structure (route inventory, per-page sections, empty states) lives in [ui-pages.md](ui-pages.md).

The aesthetic is **warm editorial**: paper-tone backgrounds, ink-line borders, serif headings, generous measure, sparse motion. The closest reference points are the visual languages of *Aeon*, *Nautilus*, *The Browser*, and *Letterform Archive* — research-journal-feeling, not SaaS-dashboard-feeling.

This document explicitly retires the legacy purple-blue gradient (`#667eea → #764ba2`) and the inline-styles-without-tokens approach. Inline styles stay (no CSS framework), but every value reads from the design tokens in `frontend/src/theme.ts`.

---

## 1. Design tokens

The token set will live at `frontend/src/theme.ts` (to be created during the redesign migration — see the 7-pass plan at the bottom of this doc). All values come from [branding.md](branding.md); this section is the **applied** version, organized by token category.

### 1.1. Colors

Every component reads from semantic roles, never raw hex. Dark mode is selected by `prefers-color-scheme` plus a manual override stored in `uiStore`.

```ts
export const colors = {
  // Surface
  bg:           { light: '#faf6f0', dark: '#1c1814' },   // page paper
  surface:      { light: '#fffaf3', dark: '#252019' },   // raised card
  surfaceAlt:   { light: '#f0e9dd', dark: '#161310' },   // sunken / chip
  // Text
  textPrimary:  { light: '#1f1b16', dark: '#e8e2d6' },
  textSecondary:{ light: '#5c5448', dark: '#a89f93' },
  textMuted:    { light: '#7d756b', dark: '#7c7264' },
  // Lines
  border:       { light: '#d8cfc0', dark: '#3a342b' },
  borderStrong: { light: '#bcae97', dark: '#544c3f' },
  // Accents
  accent:       { light: '#7a2c1a', dark: '#b04a2f' },   // oxblood
  accentSubtle: { light: '#f6e9e3', dark: '#3a1f17' },
  forest:       { light: '#2d4a3e', dark: '#5e8a78' },
  gold:         { light: '#c79945', dark: '#d8b15a' },
  // Status (warm-coherent — no bolted-on UI palette)
  success:      { light: '#2d4a3e', dark: '#5e8a78' },
  warn:         { light: '#c79945', dark: '#d8b15a' },
  error:        { light: '#7a2c1a', dark: '#b04a2f' },
  info:         { light: '#3d5a73', dark: '#7a96b0' },
  // Focus ring (always visible)
  focus:        { light: '#7a2c1a', dark: '#d8b15a' },
};
```

Component-level rules:
- **Cards** sit on `bg` and use `surface` for their fill, with a 1 px `border` outline. No drop shadows.
- **Pills / badges** use `surfaceAlt` fill + `border` outline, status-colored text.
- **Buttons** primary = `accent` fill + `bg` text; secondary = `surface` fill + `accent` text + `border` outline; tertiary (text button) = no fill, `accent` text, underline on hover.
- **Inputs** = `surface` fill, `border` outline, `accent` outline on focus (2 px), `border` on hover.

### 1.2. Type

```ts
export const fonts = {
  display: '"Fraunces", Georgia, serif',
  body:    '"Source Serif Pro", "Fraunces", Georgia, serif',
  ui:      '"Inter", system-ui, -apple-system, sans-serif',
  devanagari: '"Tiro Devanagari Hindi", "Noto Serif Devanagari", serif',
  mono:    '"JetBrains Mono", ui-monospace, "Cascadia Code", monospace',
};

export const fontSize = {
  xs:    '0.75rem',   // 12px — captions, micro-labels
  sm:    '0.875rem',  // 14px — secondary UI
  base:  '1rem',      // 16px — body
  md:    '1.125rem',  // 18px — comfortable reading
  lg:    '1.25rem',   // 20px — section headings
  xl:    '1.5rem',    // 24px — page section headers
  '2xl': '2rem',      // 32px — page titles
  '3xl': '2.75rem',   // 44px — hero, masthead
};

export const lineHeight = {
  tight: 1.2,    // headings
  snug:  1.4,    // UI
  normal:1.55,   // body
  loose: 1.7,    // long-form (reports, knowledge artifacts)
};

export const fontWeight = { regular: 400, medium: 500, semibold: 600, bold: 700 };
```

Rules:
- Headings always **display** font, weight 500–700.
- Body always **body** font, weight 400, line-height 1.55–1.7 depending on context.
- UI chrome (nav, buttons, form labels, badges) always **ui** font, weight 500.
- Numeric IDs, timestamps, code snippets always **mono**.
- The Devanagari wordmark (`प्रतिध्वनि`) always **devanagari**, never substituted.
- Long-form (reports, knowledge artifacts, Q&A answers) caps at **65–75ch** measure for readability.

### 1.3. Space

A 4-px scale.

```ts
export const space = {
  '0':  0,
  '1':  '0.25rem',  // 4
  '2':  '0.5rem',   // 8
  '3':  '0.75rem',  // 12
  '4':  '1rem',     // 16
  '5':  '1.5rem',   // 24
  '6':  '2rem',     // 32
  '7':  '2.5rem',   // 40
  '8':  '3rem',     // 48
  '10': '4rem',     // 64
  '12': '6rem',     // 96
};
```

Rules: card inner padding = `space.5`; section gap = `space.6`; button padding-x = `space.4`, padding-y = `space.2`. No magic values outside the scale.

### 1.4. Radius

```ts
export const radius = {
  none:   0,
  sm:     '4px',    // small chips, tight controls
  md:     '6px',    // default — buttons, cards
  lg:     '10px',   // hero card, modal
  pill:   '999px',  // pills, status chips
};
```

The warm-editorial aesthetic uses *less* rounding than today's UI. Sharper corners read as paper-binding, not SaaS plastic.

### 1.5. Shadow

We almost don't use shadows — borders carry the hierarchy. The single allowed shadow is for floating elements (modal, drawer, tooltip):

```ts
export const shadow = {
  none:    'none',
  hover:   '0 1px 2px rgba(31, 27, 22, 0.06)',     // subtle 2px lift on card hover
  floating:'0 8px 24px rgba(31, 27, 22, 0.18)',    // modal, drawer, dropdown
};
```

Dark mode flips to a warmer shadow color (`rgba(0, 0, 0, 0.4)` for floating).

### 1.6. Motion

```ts
export const motion = {
  duration: { fast: 120, base: 200, slow: 320 },
  easing:   { standard: 'cubic-bezier(0.2, 0.8, 0.2, 1)' },
};
```

Rules:
- All transitions use `motion.easing.standard` and one of the three durations.
- `prefers-reduced-motion: reduce` disables every transition longer than 100 ms; opacity-only fades stay.
- Page transitions: 120 ms fade-in only. No slides, no parallax.
- Hover state transitions: 120 ms.
- Modal/drawer entry: 200 ms.

### 1.7. Z-index

```ts
export const z = {
  base: 0, content: 1, sticky: 100, drawer: 200, modal: 300,
  toast: 400, tooltip: 500, debug: 999,
};
```

Single source. No ad-hoc `z-index: 9999`.

---

## 2. Layout

### 2.1. App shell

The protected pages share `AppLayout`. Today: top horizontal tab bar. Post-redesign: slim left sidebar.

```
┌──────────────────────────────────────────────────────────┐
│ [प्रतिध्वनि wordmark]  ─── (right) [LLM dot]  [user ▾]   │ ← top bar (44px)
├────────────┬─────────────────────────────────────────────┤
│  SIDEBAR   │              CONTENT                        │
│  (240px)   │                                             │
│            │   max-width: 980px (reading), 1200px (grid) │
│  collapses │                                             │
│  → 56px    │   page-padding: space.6                     │
│  on narrow │                                             │
└────────────┴─────────────────────────────────────────────┘
```

Sidebar groups (top to bottom):

```
LIBRARY
  · Shelves          (M1 — placeholder until shipped)
  · All sources
  · Channels

RESEARCH
  · New research
  · Active runs
  · History

KNOWLEDGE
  · Knowledge reports
  · Echoes (Q&A history)

AUTHOR  (greyed; unlocks at L2)
  · Books
  · Sites
  · Decks
─────────
[avatar] Settings
```

- Width: 240 px expanded, 56 px collapsed (icons only). Collapse state persists in `uiStore`.
- Active item: oxblood `accent` text + 2 px left border in `accent`. Inactive: `textSecondary`.
- Group headers: `ui` font, `xs` size, `textMuted`, uppercase, letter-spacing 0.08em.
- Keyboard shortcuts: `g + r` → research, `g + l` → library, `g + k` → knowledge, `g + a` → author. (Implemented via a global `useShortcuts` hook.)

### 2.2. Page padding & measure

- Page horizontal padding: `space.6` desktop, `space.4` tablet, `space.3` mobile.
- Reading-content max width: 65–75 ch (≈ 720–820 px).
- Card-grid max width: 1200 px.
- Forms max width: 560 px.

### 2.3. Reading-room view (reports & knowledge artifacts)

Reports are the longest single piece of content. They get the most editorial treatment:

```
┌──────────────────────────────────────────────────┐
│  TOPIC TITLE             ┌── Outline ──────────┐ │
│  by Pratidhvani          │ § 1 Introduction    │ │
│                          │ § 2 Themes          │ │
│  Drop-cap-first-paragraph│ § 3 Disagreements   │ │
│  generous measure 65-75ch│ § 4 Open questions  │ │
│  body line-height 1.7    └─────────────────────┘ │
│                                                  │
│  Inline citations as footnote chips on hover     │
│                          ┌── Reading 32% ───────┐│
└──────────────────────────└──────────────────────┘
```

- Drop cap on the first paragraph: `display` font, `3xl` size, multi-line.
- Sticky outline on the right (desktop only) with active section highlight.
- Citations render inline as small `mono`-font superscripts; hover surfaces a popover with the source title + timestamp + quote.
- Reading-progress bar floats at bottom-right; updates from scroll position.
- Print stylesheet flattens the outline, removes the progress bar, keeps citations as proper footnotes.

### 2.4. Mobile (≤ 640 px)

- Sidebar collapses to a hamburger; opens as a full-screen overlay.
- Card grids → single column.
- Reports: drop the outline, keep drop cap and citations.
- Q&A textarea: docked at bottom; chat-like.

---

## 3. Component primitives

A small, opinionated set of primitives lives at `frontend/src/components/primitives/`. Pages compose them; pages do not write raw `<div style={...}>`. Every primitive reads from tokens.

| Primitive | Notes |
|-----------|-------|
| `Button` | Variants: `primary`, `secondary`, `tertiary`, `danger`. Sizes: `sm`, `md`, `lg`. Loading state with inline spinner. Disabled state dims to `textMuted` and disables pointer events. |
| `IconButton` | Like `Button` but square; ARIA-label required. |
| `Card` | `surface` fill, `border` outline, `radius.md`. Hover variant lifts 2 px with `shadow.hover`. Optional `as` prop for `<a>` / `<button>` semantics. |
| `Input`, `Textarea`, `Select` | `surface` fill, focus ring in `accent`. Errors render `error`-colored border + helper text below. |
| `FormField` | Wraps a label + control + helper text. Generates IDs for `htmlFor`. |
| `Badge` | Pill, `surfaceAlt` fill + status text color. Sizes: `sm`, `md`. |
| `StatusPill` | Specialized Badge with semantic statuses for jobs (pending, searching, awaiting_approval, etc.). |
| `Tabs` | Underlined active tab in `accent`. Keyboard accessible (arrow keys). |
| `Modal` | Centered, `surface` fill, `shadow.floating`, focus trap, ESC-to-close, scroll lock on body. |
| `Drawer` | Slides from right, `shadow.floating`, focus trap. Used by `VideoKnowledgeDrawer`. |
| `Tooltip` | Hover/focus-triggered, `surface` fill, `shadow.floating`. ARIA-described. |
| `Spinner` | 14 px circular, `accent` color. |
| `Skeleton` | Shimmer in `surfaceAlt` with `border` outline. Variants: `text`, `paragraph`, `card`, `row`. |
| `EmptyState` | Hero-style empty state: icon + display heading + secondary line + optional CTA. The voice (per [branding.md](branding.md) §voice) is editorial — never "No data." |
| `Toast` | Slides up from bottom-right, auto-dismisses after 5 s, click to dismiss. Status-colored left border. |
| `BannerBar` | Pull-quote-style global banner for LLM down / quota warnings. Editorial, not modal. |
| `CitationChip` | Inline citation in body text. Mono superscript number → hover popover with source + timestamp + quote. |

Primitives are self-contained. They don't reach into context for theme — they import tokens directly. Theme switching (light/dark) flows via a single CSS variable layer that mirrors the token set.

---

## 4. Page chrome

### 4.1. Top bar

Top-right cluster, in order: LLM-status dot (green/yellow/red, with hover popover summarizing per-feature availability), user avatar (initials in oxblood circle) → on click, dropdown with Settings, Sign out.

### 4.2. Banner system

Driven by `useHealth()` (polls `/api/v1/health` every 60 s) plus a small `useQuota()` (60 s).

- **LLM down** → `BannerBar` with "Some features are paused" + the `unavailable_features` list, plus a "View status" link to `/settings/system`. Sticks at the top.
- **Quota soft warning (≥80%)** → softer warning, only on `/submit`.
- **Quota hard cap reached** → red banner, on `/submit`, blocks the submit button.
- **Network reconnecting** → grey banner with a spinner.

Only one banner at a time; LLM > network > quota.

### 4.3. Toast queue

Triggered by errors (React Query global `onError`), success notifications (after a successful approval, after copy-to-clipboard). Max 3 stacked; oldest auto-dismisses first.

---

## 5. Iconography

We use **Lucide** as the icon library — minimal, consistent, free. Strokes inherit `currentColor` so icons fall under the same color rules as text.

Custom icons:
- The Pratidhvani concentric-arcs glyph (per [branding.md](branding.md) §logo) lives at `frontend/src/assets/marks/echo.svg` and is the favicon + sidebar mark.

---

## 6. Imagery

- **Thumbnails** — YouTube thumbnails as-is for video sources; per-source-type cover treatment for podcasts/articles/PDFs (see [source-types.md](source-types.md)).
- **Background ornament** — sparing. The login and register pages may use a faint paper-grain texture in `surfaceAlt` over `bg`. No photographic backgrounds.
- **Empty-state illustrations** — minimal line-drawn motifs in `border` color (e.g. an empty bookshelf). One per page, opt-in. Do not over-illustrate.

---

## 7. Accessibility

- **Color contrast** — all text/background pairs above WCAG AA (4.5:1 for body, 3:1 for large text). Verified via the contrast check baked into the token-export build step.
- **Focus rings** — always visible. Never `outline: none` without a replacement.
- **Keyboard nav** — every interactive surface reachable via Tab; logical order.
- **Skip-to-content** link at the top of every page.
- **ARIA** — icon-only buttons have `aria-label`; live regions on toast and progress; `role="dialog"` on modals/drawers.
- **Screen-reader announcements** — `aria-live="polite"` on Q&A streaming output ("Answer ready"); `aria-live="assertive"` only for errors.
- **Reduced motion** — `@media (prefers-reduced-motion: reduce)` disables all > 100 ms transitions.
- **Devanagari rendering** — explicitly tested on Chromium / Firefox / Safari. Falls back to Noto Serif Devanagari if Tiro fails to load.

---

## 8. States (the page-level matrix)

Every data-bearing component declares all four states explicitly:

| State | Treatment |
|-------|-----------|
| **Empty** | `EmptyState` primitive. Editorial copy. Optional CTA. |
| **Loading** | `Skeleton` primitives matching content shape. Never a bare spinner on data. |
| **Error** | Editorial error card with retry button. Toasts for transient errors. |
| **Success / populated** | The actual content. |

Per-page mapping lives in [ui-pages.md](ui-pages.md).

---

## 9. Dark mode

Dark is full-fidelity, not a luminance flip. Every token has an explicit dark value. Behavior:

1. **Default** — match `prefers-color-scheme`.
2. **Manual override** — toggle in Settings; persists in `uiStore` + `localStorage`.
3. **Theme attribute** — applied to `<html data-theme="light|dark">`. CSS variables flip in one place.
4. **Images & illustrations** — invert SVG strokes to track text color; raster images get a subtle 0.85 brightness in dark mode to soften.

The dark variant is intentionally **inky**, not jet-black: `#1c1814` (warm dark brown, not OLED black). This keeps the editorial feel.

---

## 10. Migration plan from legacy

The current frontend is 100% inline styles with ad-hoc colors and the legacy purple-blue gradient. The redesign rolls out in passes, not pages:

1. **Pass 1 — tokens.** Land `frontend/src/theme.ts` with the full token set. Add a `<ThemeProvider>` that wires CSS variables. No page changes yet.
2. **Pass 2 — primitives.** Implement the primitive set under `components/primitives/`. Each primitive ships with a Storybook entry (or a manual `/dev/primitives` page).
3. **Pass 3 — global chrome.** Replace `AppLayout` (top-tabs → sidebar). Add `BannerBar`, the LLM dot, and the user dropdown. Order: layout shell → top bar → sidebar → mobile sheet.
4. **Pass 4 — pages.** One page at a time, in this order: Login → SubmitJob → JobsList → JobDetail → Library → LibraryQA → QAHistoryChat → Exports → Register. Each page-level PR migrates that page's inline styles to primitives + tokens; no other functional change.
5. **Pass 5 — reading room.** Reports + knowledge artifacts get the editorial treatment (drop cap, sticky outline, citation popovers, reading-progress bar).
6. **Pass 6 — accessibility audit.** Focus rings, keyboard nav, ARIA labels, screen-reader announcements, contrast verification.
7. **Pass 7 — dark mode.** Audit every page in dark; fix any contrast misses; ship the toggle.

The user-facing release is "warm editorial v1" once all 7 passes ship. Until then, individual pages may straddle styles — acceptable mid-migration, not acceptable past v1.

---

## 11. What this design is not

To keep scope honest:
- **Not a CSS framework adoption.** We stay on inline styles, just routed through tokens.
- **Not a Tailwind migration.** Considered and rejected; tokens give us 90% of Tailwind's value at 10% of the bundle cost.
- **Not a design-system library export.** We're not building Pratidhvani/UI as a separately publishable package.
- **Not a per-page theme experiment.** The aesthetic is uniform across the app. Tone variation comes from copy and content density, not visual style.
- **Not animation-heavy.** Editorial means restraint. If you find yourself adding a 4th transition, you've gone too far.

---

## 12. Cross-references

- Brand identity, palette, typography, voice, logo — [branding.md](branding.md)
- Page-level inventory and state matrix — [ui-pages.md](ui-pages.md)
- Endpoints these pages call — [api-reference.md](api-reference.md)
- Architecture & WS / auth flows — [architecture.md](architecture.md)
- Vision (the *why* behind editorial) — [vision.md](vision.md)
