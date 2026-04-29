# Pratidhvani — Marketing Site

Static landing page for `Pratidhvani` (प्रतिध्वनि — Sanskrit for *echo*),
built with [Astro](https://astro.build/). Lives outside the main app
(`backend/` + `frontend/`) so the marketing build is independent of
the product runtime.

> **Status: scaffold (2026-04-28).** This directory exists because
> [E-2.5](../docs/initiatives.md#e-25--marketing-landing-page-warm-editorial)
> just kicked off — the full content (hero, "different from
> Wikipedia" thesis, source-types matrix, install instructions, SaaS
> waitlist hook) lands in follow-up PRs (T-2.5.2 onward).

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

## Roadmap (per [E-2.5 in initiatives.md](../docs/initiatives.md#e-25--marketing-landing-page-warm-editorial))

- [x] **T-2.5.1** Astro scaffold (this PR)
- [ ] **T-2.5.2** Hero with the personal-wiki pitch + tagline
- [ ] **T-2.5.3** "How it differs from Wikipedia" section (curation thesis)
- [ ] **T-2.5.4** Source-types matrix (videos / podcasts / articles / etc.)
- [ ] **T-2.5.5** "How it works" walkthrough (search → approve → embed → ask)
- [ ] **T-2.5.6** Install instructions (open-source self-host)
- [ ] **T-2.5.7** SaaS waitlist hook (future-only — disabled CTA today)
- [ ] **T-2.5.8** Footer: GitHub, docs, license

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
