import { createLogger, defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { noteFailedRequestMethod, withoutProxyPaths } from './viteProxyLog'

// Where the dev proxy sends /api and /ws. Override when the backend runs on
// another port (a worktree's live check beside the main checkout on 8000):
//   VITE_PROXY_TARGET=http://localhost:8001 npm run dev -- --port 5174
const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000'
const wsTarget = proxyTarget.replace(/^http/, 'ws')

// An absolute path on purpose: a bare `html-dom-parser/...` specifier would go
// back through the package's exports map, whose `require` condition hands the
// CommonJS file straight back.
const htmlDomParserClient = fileURLToPath(
  new URL('./node_modules/html-dom-parser/esm/client/html-to-dom.mjs', import.meta.url),
)

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The proxy's failed-request line keeps its method and stack and leaves the
  // path out, which can hold a search's words or a fact's key (T-4.11.4.10).
  // Vite skips its own logLevel and clearScreen handling for a custom logger,
  // so a level would go to createLogger here; nothing passes one today.
  customLogger: withoutProxyPaths(createLogger()),
  resolve: {
    alias: [
      // html-react-parser's entry is CommonJS and requires html-dom-parser,
      // whose CommonJS client file declares a local `require_node`. Vite 8's
      // dependency optimizer names its own CommonJS module wrappers the same
      // way, so the pre-bundle ends up with `var require_node = require_node()`
      // and the app throws at import in dev (the production build is fine).
      // Pointing the dependency at html-dom-parser's ESM client entry, which
      // is what the browser condition selects anyway, sidesteps the collision.
      { find: /^html-dom-parser$/, replacement: htmlDomParserClient },
    ],
  },
  server: {
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        configure: noteFailedRequestMethod,
      },
      '/ws': {
        target: wsTarget,
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
