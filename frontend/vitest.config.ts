import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const htmlDomParserClient = fileURLToPath(
  new URL('./node_modules/html-dom-parser/esm/client/html-to-dom.mjs', import.meta.url),
);

// Unit tests for pure frontend modules (the reader's sanitiser and parser
// first, S-8.8.1). jsdom gives DOMPurify a window; nothing here starts a
// browser. `npm test` runs them once; `npx vitest` watches.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      // Same alias as vite.config.ts: tests then exercise the DOM-based client
      // parser the browser uses (under jsdom) rather than the htmlparser2
      // server build.
      { find: /^html-dom-parser$/, replacement: htmlDomParserClient },
    ],
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
