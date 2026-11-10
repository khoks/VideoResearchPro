/**
 * The dev proxy's failed-request line, without the request's path
 * (T-4.11.4.10).
 *
 * Under scripts/start.ps1 the browser reaches the API through Vite's dev
 * proxy. While the backend is down or restarting, Vite 8 logs each failed
 * request as `http proxy error: <req.url>` and the error's stack, to
 * .frontend.err.log. A URL can hold a user's words: `?q=` search words, or a
 * fact's key in `DELETE /api/v1/echo/context/{kind}/{key}`, which the API's
 * own access log already writes by their length (D-168, D-171).
 *
 * A `configure(proxy)` hook cannot stop that line: Vite adds its own 'error'
 * listener after `configure`, and both fire. The line does pass through the
 * logger, so `withoutProxyPaths` rewrites it as
 * `http proxy error: DELETE [path left out]` and keeps the stack, which says
 * how the backend failed (`ECONNREFUSED`, `socket hang up`). For the errors a
 * proxy meets the stack holds no path; if one ever does, every copy of the URL
 * Vite was given is taken out of it too. Every other line goes through as it
 * came, warnings and errors included, and no line is dropped.
 *
 * Vite's other proxy lines (`ws proxy error:`, `ws proxy socket error:` and
 * `ws proxy bypass error:`) name no URL, so they go through unchanged.
 */
import type { Logger, ProxyOptions } from 'vite'

export const PATH_LEFT_OUT = '[path left out]'

const KIND = 'http proxy error: '

// An SGR escape: picocolors colours the line red, on Windows in a log file too.
const SGR = '\\u001b\\[[0-9;]*m'
const PROXY_ERROR_LINE = new RegExp(`^((?:${SGR})*)${KIND}(.*?)((?:${SGR})*)$`)

// The method of each request the proxy failed, by its error. Vite's line
// carries the URL alone, but its listener receives the same error object.
const methodByError = new WeakMap<object, string>()

/**
 * A proxy `configure` hook: notes each failed request's method for the logger.
 * It runs before Vite's own listener, which is added after `configure`.
 */
export const noteFailedRequestMethod: NonNullable<ProxyOptions['configure']> = (proxy) => {
  proxy.on('error', (err, req) => {
    if (typeof err === 'object' && err !== null && typeof req?.method === 'string') {
      methodByError.set(err, req.method)
    }
  })
}

/** The forms of `url` taken out of a stack: as Vite was given it, and decoded. */
function urlForms(url: string): string[] {
  // A bare `/` holds no words, and would match every slash in the stack.
  if (url.length < 2) return []
  const forms = [url]
  try {
    const decoded = decodeURIComponent(url)
    if (decoded !== url) forms.push(decoded)
  } catch {
    // A malformed escape: the URL as given is the only form.
  }
  return forms
}

/**
 * `msg` with the request's path left out when it is the proxy's
 * `http proxy error` line, and `msg` itself otherwise.
 */
export function leaveProxyPathOut(msg: string, error?: unknown): string {
  if (typeof msg !== 'string') return msg
  const newline = msg.indexOf('\n')
  const head = newline === -1 ? msg : msg.slice(0, newline)
  const match = PROXY_ERROR_LINE.exec(head)
  if (!match) return msg
  const [, open, url, close] = match
  const method = typeof error === 'object' && error !== null ? methodByError.get(error) : undefined
  let stack = newline === -1 ? '' : msg.slice(newline)
  for (const form of urlForms(url)) stack = stack.split(form).join(PATH_LEFT_OUT)
  return `${open}${KIND}${method ? `${method} ` : ''}${PATH_LEFT_OUT}${close}${stack}`
}

/**
 * `logger`, with the proxy's failed-request line rewritten by
 * `leaveProxyPathOut`. Each call reaches `logger` once, with its options.
 */
export function withoutProxyPaths(logger: Logger): Logger {
  return {
    info: (msg, options) => logger.info(leaveProxyPathOut(msg), options),
    warn: (msg, options) => logger.warn(leaveProxyPathOut(msg), options),
    warnOnce: (msg, options) => logger.warnOnce(leaveProxyPathOut(msg), options),
    error: (msg, options) => logger.error(leaveProxyPathOut(msg, options?.error), options),
    clearScreen: (type) => logger.clearScreen(type),
    hasErrorLogged: (error) => logger.hasErrorLogged(error),
    get hasWarned() {
      return logger.hasWarned
    },
    set hasWarned(value) {
      logger.hasWarned = value
    },
  }
}
