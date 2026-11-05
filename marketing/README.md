# Pratidhvani — Marketing Site

Static landing page for `Pratidhvani` (प्रतिध्वनि — Sanskrit for *echo*),
built with [Astro](https://astro.build/). Lives outside the main app
(`backend/` + `frontend/`) so the marketing build is independent of
the product runtime.

> **Status: shipped ([E-2.5](../docs/initiatives.md#e-25--marketing-landing-page-warm-editorial)).** One page, `src/pages/index.astro`, with the logos in `public/`. Deploying it waits on a hosting decision (M-2.5). This is a separate build from the `/landing` and `/pricing` pages inside the app.

## Why a separate sub-project

- **Static output** — the marketing site builds to plain HTML / CSS / JS.
  No backend, no auth, no database; deployable to any static host
  (Netlify / Vercel / GitHub Pages / Cloudflare Pages) without the
  Pratidhvani runtime.
- **Independent dependency tree** — Astro lives in
  `marketing/node_modules`, not the React app's. Either side can
  upgrade without touching the other.
- **Shared visual identity** — the warm-editorial palette comes from
  `docs/branding.md`. Token values may eventually be exported from
  `frontend/src/theme.ts` so the site and the app stay perfectly in
  sync (E-2.5 T-2.5.x — exact mechanism TBD).

## Develop

```bash
cd marketing
npm install        # one-time; resolves the Astro dependency tree
npm run dev        # http://localhost:4321
```

## Build for production

```bash
cd marketing
npm run build      # outputs to ./dist
npm run preview    # serves dist/ locally to verify
```

CI runs the same build on every pull request (the `marketing` job in
`.github/workflows/ci.yml`).

## Sections

Hero, how it differs from Wikipedia, the source-types matrix, how it works, install instructions, the SaaS waitlist hook (a disabled call to action for now) and the footer. The board's [E-2.5](../docs/initiatives.md#e-25--marketing-landing-page-warm-editorial) has the history.

## Why Astro and not Next / 11ty / plain HTML

- **Astro** ships zero JS by default, generates clean static output,
  has first-class support for component islands when interactivity is
  needed (e.g. the SaaS waitlist signup), and treats Markdown / MDX
  as first-class so the editorial-tone copy can live in `.md` files
  alongside the structural `.astro` pages.
- **Next.js** is overkill for a static site and biases toward
  React-first thinking; the marketing site has no React state.
- **11ty** is a viable alternative; rejected because Astro's TypeScript +
  components-as-files DX is cleaner for solo / small-team
  iteration.
- **Plain HTML** loses the partial / layout / collection abstractions
  that make multi-page sites tractable.

## Design references

- [Brand & visual identity (docs/branding.md)](../docs/branding.md) — palette, type, voice
- [Roadmap (docs/feature-roadmap.md)](../docs/feature-roadmap.md) — overall product trajectory
- [Vision (docs/vision.md)](../docs/vision.md) — *why* the product exists
