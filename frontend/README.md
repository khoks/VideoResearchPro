# Pratidhvani frontend

React 19, TypeScript and Vite, with TanStack React Query for server state, Zustand for UI state and React Router v7. Every style is inline, with its values from `src/theme.ts`.

Project setup is in [docs/contributing.md](../docs/contributing.md). The pages and their routes are in [docs/ui-pages.md](../docs/ui-pages.md), the design system in [docs/ui-design.md](../docs/ui-design.md).

```bash
npm install
npm run dev          # dev server at http://localhost:5173
npm run build        # production build and type check
npm test             # vitest
npm run test:mobile  # Playwright device suite
npm run lint
```

The dev server proxies `/api` to port 8000. To point it elsewhere, set `VITE_PROXY_TARGET` in the shell: `vite.config.ts` reads `process.env`, which a `.env` file does not fill.
