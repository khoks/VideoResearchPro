// @ts-check
import { defineConfig } from 'astro/config';

/**
 * Pratidhvani marketing-site Astro config.
 *
 * Static-only build under `dist/`. Output target is the warm-editorial
 * brand identity per docs/branding.md. Site URL placeholder lives in
 * the env (or hardcoded once T-2.6.4 finalizes the domain choice
 * — `pratidhvani.app` / `pratidhvani.so` / `pratidhvani.dev` are the
 * candidates per the original plan §7).
 */
export default defineConfig({
  site: 'https://pratidhvani.app',
  output: 'static',
  build: {
    format: 'directory',
  },
  // Enable strict TS checks at build time for the few .ts utilities
  // any future page might add.
  compressHTML: true,
});
