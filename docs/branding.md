# Pratidhvani — Brand & Visual Identity

**Status:** approved (2026-04-24). This document is the source of truth that `frontend/src/theme.ts` and all marketing assets mirror.

---

## 1. Name

**`प्रतिध्वनि` — `Pratidhvani`** — Sanskrit/Hindi for *echo*.

The name is fixed. Earlier internal placeholders (VideoResearchPro, working candidates like Marginalia / Folio / Lore) are retired.

### Why "echo"

Echo names what the product fundamentally does:

- **Sources echo into your library.** Every video, podcast, article, thread, or book the user ingests is a voice resounding into their personal collection.
- **Your library echoes back when you ask.** Q&A retrieves and replays the relevant fragments — citation-grounded, in the speaker's own words.
- **Past Q&As echo into future ones.** The `qa_library_global` ChromaDB collection means every question informs the next; the personal-brain north-star (see [vision.md](vision.md)) is, in essence, a long-running echo of the user's life.
- **Echoes are personal.** A canyon's echo depends on where you stand. A user's echo depends on which sources they have chosen — the "non-official sources, your curation" thesis becomes the literal name.
- **Devanagari adds character.** Distinctive in a sea of generic English-Latin SaaS names; reads as cultured/literary, perfectly aligned with the warm-editorial visual direction.

### Latin transliteration

Canonical: **`Pratidhvani`** (no macron, no `w`).

Acceptable in informal contexts: `Pratidhwani` (older spelling). Not used: `Pratidhvāni` (macron), `Dhvani` (short form — reserved for possible future sub-brand meaning "sound").

### Lockup rules

- **Hero / masthead**: full Devanagari `प्रतिध्वनि` set in a literary Devanagari serif, with `Pratidhvani` (Latin) underneath in a warm italic serif as a secondary line.
- **In-app sidebar (expanded)**: `प्रतिध्वनि` Devanagari + a single line of body text underneath: `Pratidhvani`.
- **Sidebar collapsed / favicon / app icon / social embed**: glyph mark only (see §3).
- **Plain text (terminal output, log lines, env names)**: `pratidhvani` in lowercase Latin.

---

## 2. Tagline

| Use | Tagline |
|-----|---------|
| Hero (open-source phase) | *Your sources, echoed back.* |
| Subhead / about page | *The echo of your chosen knowledge.* |
| Personal-brain milestone | *प्रतिध्वनि — your second brain, in your own voice.* |
| Short variant (sidebar tooltip) | *Curate the voices. Ask the echo.* |

The hero tagline is the durable one. The personal-brain tagline ships when L3 (see [feature-roadmap.md](feature-roadmap.md)) lands.

---

## 3. Logo

### Wordmark

- **Devanagari**: `प्रतिध्वनि` set in a literary Devanagari serif. Candidates (in order of preference): Tiro Devanagari Hindi, ITF Devanagari, Yatra One. A custom-cut letterform of just the central syllable `ध्व` (dhva) is the long-term aspiration.
- **Latin**: `Pratidhvani` in **Fraunces** italic, optical size 14, weight 500, letter-spacing −0.01em. Set lowercase.

### Glyph mark (the "echo mark")

The recommended glyph for favicon / sidebar-collapsed / app icon:

**Concentric arcs** — three nested half-arcs of decreasing weight, opening leftward, suggesting a sound returning. The outermost arc is full-strength accent primary (`#7a2c1a`), the middle arc 65% opacity, the innermost arc 35% opacity — the *fade* of an echo. SVG-trivial; works at 16px favicon size.

Alternates documented for future evaluation (not currently shipping):

1. **Doubled letterform** — the syllable `ध्व` set twice, the second a faded ghost shifted slightly.
2. **Canyon profile** — two facing curves like a valley cross-section, sound bouncing between them.
3. **Margin-mark + return** — an opening quote `"` paired with a softer reflected closing one beneath.

### Hard avoids

These are explicitly off-limits to keep us out of generic-AI-product territory:

- ❌ Sparkles / four-pointed-star "AI" glyphs
- ❌ Neural-net node-and-edge patterns
- ❌ Brain-with-circuits illustrations
- ❌ Gradient blurs / chromatic aberration
- ❌ Waveform ribbons (too literal, reads as "audio app")
- ❌ Books with floating pages / paper-airplane motifs

---

## 4. Color tokens

The product is warm-editorial. Today's purple-blue gradient (`#667eea → #764ba2`) is **retired** in favour of a paper-and-ink palette with a single oxblood accent.

### Light mode (default)

| Role | Hex | Usage |
|------|-----|-------|
| `bg.page` | `#faf6f0` | Application background — warm off-white paper |
| `bg.surface` | `#fffaf3` | Raised cards, modals |
| `bg.sunken` | `#f0e9dd` | Sunken panels, code blocks, alt rows |
| `text.primary` | `#1f1b16` | Body text, headings — deep warm graphite |
| `text.secondary` | `#5c5448` | Secondary copy, metadata |
| `text.muted` | `#7d756b` | Hints, disabled, timestamps |
| `border.line` | `#d8cfc0` | 1px ink-line borders on cards & inputs |
| `border.strong` | `#a89f93` | Stronger separator (rare) |
| `accent.primary` | `#7a2c1a` | Oxblood / library-binding red — primary CTAs, focus rings, active state |
| `accent.secondary` | `#2d4a3e` | Forest-teal — secondary buttons, success badges |
| `accent.highlight` | `#c79945` | Vintage gold — emphasis, "new" badges, warning state |
| `status.success` | `#2d4a3e` | Completed jobs, healthy LLMs |
| `status.warn` | `#c79945` | Awaiting approval, degraded LLMs |
| `status.error` | `#7a2c1a` | Failed jobs, down LLMs |
| `status.info` | `#3d5a73` | Running / progress |

### Dark mode

| Role | Hex | Usage |
|------|-----|-------|
| `bg.page` | `#1c1814` | Inky brown background |
| `bg.surface` | `#252019` | Raised cards, modals |
| `bg.sunken` | `#161310` | Sunken panels |
| `text.primary` | `#e8e2d6` | Cream body text |
| `text.secondary` | `#a89f93` | Secondary |
| `text.muted` | `#7c7264` | Hints, disabled |
| `border.line` | `#3a342b` | Ink-line border |
| `border.strong` | `#5c5448` | Stronger separator |
| `accent.primary` | `#b04a2f` | Lifted oxblood for contrast |
| `accent.secondary` | `#5e8a78` | Lifted forest-teal |
| `accent.highlight` | `#d8b15a` | Lifted gold |
| `status.success` | `#5e8a78` | |
| `status.warn` | `#d8b15a` | |
| `status.error` | `#b04a2f` | |
| `status.info` | `#7a96b0` | |

### Token mapping in code

These tokens live in `frontend/src/theme.ts` (to be created). Inline style props read from the `colors` object exported there. The CSS variables in [frontend/src/index.css](../frontend/src/index.css) are rewritten to mirror these tokens; the `[data-theme="dark"]` selector flips them.

No component should ever hard-code a hex value that isn't a token.

---

## 5. Typography

### Font stack

| Role | Family | Notes |
|------|--------|-------|
| Display & headings | **Fraunces** (variable) | Warm, slightly editorial. Use higher optical size for masthead, lower for h2/h3. |
| Body reading (reports, knowledge artifacts, Q&A answers) | **Source Serif Pro** | Generous measure (60-75ch); line-height 1.65. Drop-cap on first paragraph of long-form. |
| Devanagari | **Tiro Devanagari Hindi** | Pairs visually with Fraunces; serif character; legible at small sizes. |
| UI sans (forms, nav, badges, lists, dashboards) | **Inter** | Neutral, accessible, broad weight range. |
| Mono (code, IDs, timestamps, env vars) | **JetBrains Mono** | Single mono throughout. |

All fonts are self-hosted via Google Fonts or hosted locally; no remote-runtime dependency at app load time (offline-first for the self-host phase).

### Type scale

Modular scale anchored on 1rem = 16px. No ad-hoc font-sizes anywhere in the codebase.

| Token | Size (rem) | Pixels (default 16px root) | Use |
|-------|-----------|---------------------------|-----|
| `xs`  | 0.75      | 12 | Captions, metadata |
| `sm`  | 0.875     | 14 | Secondary copy, form labels |
| `base`| 1.0       | 16 | Body |
| `md`  | 1.125     | 18 | Long-form reading |
| `lg`  | 1.25      | 20 | h4 |
| `xl`  | 1.5       | 24 | h3 |
| `2xl` | 2.0       | 32 | h2 |
| `3xl` | 2.75      | 44 | h1 / masthead |

### Line-height & measure

| Context | Line-height | Measure |
|---------|-------------|---------|
| UI / dashboards | 1.4 | n/a |
| Body reading | 1.6 | 60-72ch |
| Long-form (reports, knowledge artifacts) | 1.7 | 65-75ch |
| Headings | 1.2 | n/a |

### Drop-cap

Long-form artifacts (reports, knowledge artifacts) get a drop-cap on the first paragraph of each section. Implementation: pure CSS `::first-letter { float: left; font-size: 3.5em; line-height: 0.9; padding-right: 0.05em; color: var(--accent-primary); font-family: 'Fraunces'; font-weight: 700; }`.

---

## 6. Spacing, radius, motion

### Spacing scale (rem)

`0.25 / 0.5 / 0.75 / 1 / 1.5 / 2 / 3 / 4 / 6 / 8`. Tokens: `space.1` … `space.10`. No ad-hoc paddings.

### Radius

| Token | Value | Use |
|-------|-------|-----|
| `radius.sm` | `4px` | Inputs, badges |
| `radius.md` | `8px` | Buttons |
| `radius.lg` | `12px` | Cards |
| `radius.xl` | `16px` | Modals |
| `radius.full` | `9999px` | Pills, avatars |

### Shadow

Subtle, warm-toned. No big drop-shadows; the hierarchy is communicated by ink-line borders + 2px lift on hover.

| Token | Value |
|-------|-------|
| `shadow.subtle` | `0 1px 2px rgba(31, 27, 22, 0.06)` |
| `shadow.lift`   | `0 2px 8px rgba(31, 27, 22, 0.08)` |
| `shadow.modal`  | `0 12px 40px rgba(31, 27, 22, 0.18)` |

### Motion

| Token | Duration | Easing | Use |
|-------|----------|--------|-----|
| `motion.fast` | `120ms` | `ease-out` | Hover states, focus rings |
| `motion.base` | `200ms` | `ease-out` | Page transitions, accordion |
| `motion.slow` | `400ms` | `ease-in-out` | Modals enter/exit |

All motion respects `@media (prefers-reduced-motion: reduce)` — durations collapse to `0ms`.

---

## 7. Voice & copy

### Words we use

| Concept | Word |
|---------|------|
| A research run | "Research" or "research run" (avoid "Job" in user-facing copy) |
| The list of past research | "Your library" |
| A grouping / project / folder | "Shelf" / "Shelves" |
| User-authored annotation on a source | "Note" |
| Q&A turn | "Exchange" |
| Q&A history meta-chat | "Echoes" (poetic flourish, used sparingly) |
| Source content | "Source", "volume" (book-y), "document" (technical) |

### Words we avoid

- "Job" (in user-facing copy — fine in code/internal docs)
- "Pipeline", "ingest", "workflow" (in user-facing copy)
- "AI-powered", "leverage", "synergy", "platform"
- "Dashboard" (we have a library, not a dashboard)
- Generic "Try it now" / "Get started" CTAs — prefer task-grounded: "Begin a research run" / "Add your first source"

### Empty states

Empty states match the editorial voice. Not "No data found" — instead:

- Library empty: *No volumes on your shelf yet. Begin a research run to start building your library.*
- Q&A history empty: *No echoes yet. Ask your first question to begin.*
- Channels empty: *No subscribed channels. Add your first source by URL above.*
- Knowledge artifacts empty: *No knowledge reports generated yet. Click "Generate" on any video to extract its structured knowledge.*

### Error states

Editorial, never blame-y, never tech-jargon-only:

- LLM down: *Q&A is paused — your `qa_formulate_answer` use case is unreachable. [Retry] [View status]*
- Quota hit: *Your YouTube quota is exhausted for the day. New research will resume tomorrow at 00:00 UTC.*

---

## 8. Asset inventory

Files of the brand rollout. **Shipped 2026-10-19 with S-8.12.2:** the favicon, the Apple touch icon, the mark-only logo, the manifest (plus 192 / 512 / maskable PNGs under `frontend/public/icons/`) and the page title, all from the §3 echo mark, re-rendered from `logo-mark.svg` by `npm run icons`. [D-112](decisions.md#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) made that mark the identity. **Made 2026-11-04 (T-2.8.2, T-2.8.4):** the full lockup and the marketing set, which also gives the marketing site the favicon its layout links to. The Open Graph image waits until M11 is scheduled (T-2.8.3).

**The owner has not seen the 2026-11-04 artwork.** It was checked by rendering it, not by the person whose brand it is. Treat it as a proposal until they have.

| Asset | Path | Notes |
|-------|------|-------|
| Favicon | `frontend/public/favicon.svg` | Concentric-arcs glyph mark, dark/light variants |
| Apple touch icon | `frontend/public/apple-touch-icon.png` | 180×180 |
| Open Graph image | `frontend/public/og.png` | 1200×630, masthead lockup over paper bg. Not made yet: waits for M11 (T-2.8.3) |
| Logo SVG (full lockup) | `frontend/public/logo-full.svg` | Mark + Devanagari + Latin, text outlined. For light backgrounds |
| Logo SVG (full lockup, dark) | `frontend/public/logo-full-dark.svg` | The same drawing in the dark tokens |
| Logo SVG (mark only) | `frontend/public/logo-mark.svg` | Concentric arcs. The master: every logo and app icon comes from it |
| Logo SVG (mark only, dark) | `frontend/public/logo-mark-dark.svg` | The master's arcs in the dark accent |
| Manifest | `frontend/public/manifest.webmanifest` | Update `name`, `short_name`, `theme_color: #7a2c1a` |
| Page title | `frontend/index.html` | `<title>Pratidhvani — Your sources, echoed back.</title>` |
| Marketing full lockup | `marketing/public/logo-full.svg`, `marketing/public/logo-full-dark.svg` | Same files as the app's |
| Marketing mark | `marketing/public/logo-mark.svg`, `marketing/public/logo-mark-dark.svg` | Same files as the app's |
| Marketing favicon | `marketing/public/favicon.svg` | The app's favicon; `marketing/src/layouts/BaseLayout.astro` links it |

These are tracked in [feature-roadmap.md](feature-roadmap.md) as a "rebrand asset rollout" milestone, not part of the doc-refresh phase.

### How the full lockup is built

- **The wordmarks follow §3:** Tiro Devanagari Hindi Regular, and Fraunces Italic at optical size 14, weight 500, letter-spacing −0.01em, lowercase.
- **§3 sets no colours, so the lockup takes the app's:** Devanagari in `accent.primary`, Latin in `text.secondary`. The Astro site sets its Devanagari in `text.primary`.
- **Layout:** the mark at its master size, the text block exactly as tall as the mark's ink, both wordmarks on one left edge.
- **Smallest size: 32 px tall.** Below that the Latin line stops being legible at 1× pixels. Use the mark alone (§1).
- **Dark is a separate file, not a media query:** `prefers-color-scheme` follows the operating system, and the app's theme is a toggle on `data-theme`.
- **The live pages set the Latin line differently from §3:** roman capitals, tracked wide, in `frontend/src/layouts/AppLayout.tsx`, `frontend/src/components/auth/AuthShell.tsx` and `frontend/src/pages/marketing/`, and roman mixed case on the Astro site. The logo follows §3. One of the two should change, and that is the owner's call.

The text is outlines, shaped by HarfBuzz, so no logo depends on an installed font. To change the artwork, change `logo-mark.svg` or the constants in `frontend/scripts/outline-logos.py` and regenerate (its header has the steps); do not edit the SVGs by hand. `backend/tests/test_ci/test_brand_assets.py` holds the files to the master, the tokens and the shaping, and pins both wordmarks' outlines, so a regeneration that changes them fails until someone has rendered the result, looked at it and updated `WORDMARK_SHA256`.

### Fonts behind the outlines

| Wordmark | Font | Taken from | Licence |
|----------|------|------------|---------|
| Devanagari | Tiro Devanagari Hindi Regular, version 1.52, © The Indigo Project Authors | npm `@fontsource/tiro-devanagari-hindi@5.3.0` | SIL OFL 1.1 |
| Latin | Fraunces Italic variable, version 1.000, © The Fraunces Project Authors | npm `@fontsource-variable/fraunces@5.3.0` | SIL OFL 1.1 |

Outlining is allowed: the OFL's terms do "not apply to any document created using the Font Software", and neither font declares a Reserved Font Name. No font file is in the repository.

---

## 9. Cross-references

- The full vision behind the name lives in [vision.md](vision.md).
- The UI tokens table reappears (with code-level token names) in [ui-design.md](ui-design.md).
- Per-page wireframes using these tokens live in [ui-pages.md](ui-pages.md).
- Roadmap milestones referencing the asset rollout live in [feature-roadmap.md](feature-roadmap.md).
