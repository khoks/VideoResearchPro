// @vitest-environment node
/*
 * The dev proxy's failed-request line leaves the request's path out
 * (T-4.11.4.10). The unit half drives the logger with the lines Vite 8.0.3's
 * proxy middleware writes, word for word; the production half starts a real
 * Vite dev server from vite.config.ts, its proxy pointed at a closed port, and
 * reads what the server prints for requests that carry a user's words.
 */
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createLogger, createServer, type InlineConfig, type Logger, type ProxyOptions } from 'vite';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PATH_LEFT_OUT, leaveProxyPathOut, noteFailedRequestMethod, withoutProxyPaths } from './viteProxyLog';

const FRONTEND = path.dirname(fileURLToPath(import.meta.url));

// What picocolors' red() wraps a line in.
const RED = (text: string) => `\u001b[31m${text}\u001b[39m`;
// eslint-disable-next-line no-control-regex -- the escapes are what it strips
const plain = (text: string) => text.replace(/\u001b\[[0-9;]*m/g, '');

const SEARCH = '/api/v1/search?q=zebra%20quilt%20marmalade&types=note';
const FACT = '/api/v1/echo/context/interest/kumquat%20larkspur';
const WORDS = ['zebra', 'quilt', 'marmalade', 'kumquat', 'larkspur'];

// The stacks the real check saw for each way a backend fails.
const STACKS = {
  refused: 'AggregateError [ECONNREFUSED]: \n    at internalConnectMultiple (node:net:1134:18)\n    at afterConnectMultiple (node:net:1715:7)',
  reset:
    'Error: write ECONNRESET\n    at afterWriteDispatched (node:internal/stream_base_commons:159:15)\n    at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1622:10)',
  hangUp: 'Error: socket hang up\n    at Socket.socketOnEnd (node:_http_client:599:25)\n    at Socket.emit (node:events:520:35)',
  timedOut: 'Error: socket hang up\n    at Socket.socketCloseListener (node:_http_client:548:27)\n    at TCP.<anonymous> (node:net:346:12)',
};

/** Vite's own line, as proxyMiddleware writes it: `http proxy error: ${res.req.url}\n${err.stack}`. */
const viteLine = (url: string, stack: string) => `${RED(`http proxy error: ${url}`)}\n${stack}`;

function fakeLogger() {
  const base = {
    info: vi.fn(),
    warn: vi.fn(),
    warnOnce: vi.fn(),
    error: vi.fn(),
    clearScreen: vi.fn(),
    hasErrorLogged: vi.fn(() => true),
    hasWarned: false,
  };
  return { base, logger: withoutProxyPaths(base as unknown as Logger) };
}

/** An error the proxy failed a request with, its method noted as Vite's configure hook would. */
function failedRequest(method: string, stack: string) {
  const err = Object.assign(new Error('refused'), { stack });
  const proxy = new EventEmitter();
  noteFailedRequestMethod(proxy as unknown as Parameters<NonNullable<ProxyOptions['configure']>>[0], {});
  proxy.emit('error', err, { method }, {});
  return err;
}

describe('the proxy line', () => {
  for (const [kind, stack] of Object.entries(STACKS)) {
    it(`leaves a query's words out and keeps the method and the ${kind} stack`, () => {
      const { base, logger } = fakeLogger();
      const err = failedRequest('GET', stack);
      const options = { timestamp: true, error: err };
      logger.error(viteLine(SEARCH, stack), options);

      expect(base.error).toHaveBeenCalledTimes(1);
      const [msg, passed] = base.error.mock.calls[0];
      expect(msg).toBe(`${RED(`http proxy error: GET ${PATH_LEFT_OUT}`)}\n${stack}`);
      expect(passed).toBe(options);
      for (const word of WORDS) expect(msg).not.toContain(word);
    });

    it(`leaves a path's words out and keeps the method and the ${kind} stack`, () => {
      const { base, logger } = fakeLogger();
      const err = failedRequest('DELETE', stack);
      logger.error(viteLine(FACT, stack), { timestamp: true, error: err });

      const [msg] = base.error.mock.calls[0];
      expect(msg).toBe(`${RED(`http proxy error: DELETE ${PATH_LEFT_OUT}`)}\n${stack}`);
      expect(msg).not.toContain('/api/v1/echo/context');
      for (const word of WORDS) expect(msg).not.toContain(word);
    });
  }

  it('leaves the path out with no method when none was noted', () => {
    const { base, logger } = fakeLogger();
    logger.error(viteLine(SEARCH, STACKS.refused), { timestamp: true, error: new Error('refused') });
    expect(base.error.mock.calls[0][0]).toBe(`${RED(`http proxy error: ${PATH_LEFT_OUT}`)}\n${STACKS.refused}`);
  });

  it('reads the line uncoloured too, and with no stack', () => {
    expect(leaveProxyPathOut(`http proxy error: ${FACT}`)).toBe(`http proxy error: ${PATH_LEFT_OUT}`);
    expect(leaveProxyPathOut(`http proxy error: ${SEARCH}\n${STACKS.hangUp}`)).toBe(
      `http proxy error: ${PATH_LEFT_OUT}\n${STACKS.hangUp}`,
    );
  });

  it('takes the URL it was given out of a stack that holds it, as given and decoded', () => {
    const stack = [
      `TypeError: Failed to parse URL from http://localhost:8000${SEARCH}`,
      `    cause: Error: no route for ${decodeURIComponent(FACT)}`,
      '    at stream2 (node_modules/vite/dist/node/chunks/node.js:17228:30)',
    ].join('\n');
    const searchOut = leaveProxyPathOut(viteLine(SEARCH, stack));
    expect(plain(searchOut).split('\n')[1]).toBe(`TypeError: Failed to parse URL from http://localhost:8000${PATH_LEFT_OUT}`);
    const factOut = leaveProxyPathOut(viteLine(FACT, stack));
    expect(plain(factOut).split('\n')[2]).toBe(`    cause: Error: no route for ${PATH_LEFT_OUT}`);
    for (const word of ['kumquat', 'larkspur']) expect(factOut).not.toContain(word);
    // Only the URL it was given: the frames stay as they were.
    expect(factOut).toContain('at stream2 (node_modules/vite/dist/node/chunks/node.js:17228:30)');
  });

  it('leaves a stack whole for a bare slash, and takes out a URL that will not decode as given', () => {
    // This stack's frames hold slashes of their own (node:internal/...).
    expect(leaveProxyPathOut(viteLine('/', STACKS.reset))).toBe(viteLine(PATH_LEFT_OUT, STACKS.reset));
    const broken = '/api/v1/search?q=%E0%A4';
    expect(leaveProxyPathOut(viteLine(broken, `Error: ${broken}`))).toBe(viteLine(PATH_LEFT_OUT, `Error: ${PATH_LEFT_OUT}`));
  });

  it('goes the same way through info, warn and warnOnce', () => {
    const { base, logger } = fakeLogger();
    logger.info(viteLine(SEARCH, STACKS.refused));
    logger.warn(viteLine(FACT, STACKS.refused));
    logger.warnOnce(viteLine(FACT, STACKS.refused));
    for (const method of [base.info, base.warn, base.warnOnce]) {
      expect(method).toHaveBeenCalledTimes(1);
      expect(method.mock.calls[0][0]).toBe(viteLine(PATH_LEFT_OUT, STACKS.refused));
    }
  });
});

describe('every other line', () => {
  const unrelated: Array<['info' | 'warn' | 'warnOnce' | 'error', string]> = [
    ['info', `  \u001b[32m➜\u001b[39m  \u001b[1mLocal\u001b[22m:   \u001b[36mhttp://localhost:5173/\u001b[39m`],
    ['info', `\u001b[32mpage reload \u001b[39m\u001b[2msrc/pages/LibraryPage.tsx\u001b[22m`],
    ['warn', '\u001b[33m(!) Some chunks are larger than 500 kB after minification.\u001b[39m'],
    ['warnOnce', 'The plugin "vite-tsconfig-paths" is detected.'],
    ['error', `${RED('Internal server error: Failed to resolve import "./Missing" from "src/main.tsx".')}\n  Plugin: vite:import-analysis`],
    ['error', `${RED('ws proxy error:')}\n${STACKS.refused}`],
    ['error', `${RED('ws proxy socket error:')}\n${STACKS.reset}`],
    ['error', `${RED('ws proxy bypass error:')}\nError: bypass threw\n    at bypass (vite.config.ts:1:1)`],
    ['error', 'A line that quotes http proxy error: /api/v1/search?q=x past its start'],
  ];

  for (const [method, msg] of unrelated) {
    it(`passes through unchanged: ${method} ${JSON.stringify(plain(msg).slice(0, 40))}`, () => {
      const { base, logger } = fakeLogger();
      const options = { timestamp: true, error: new Error('x') };
      logger[method](msg, options);
      expect(base[method]).toHaveBeenCalledTimes(1);
      expect(base[method].mock.calls[0][0]).toBe(msg);
      expect(base[method].mock.calls[0][1]).toBe(options);
    });
  }

  it('drops nothing: each call reaches the logger once, whatever it carries', () => {
    const { base, logger } = fakeLogger();
    const calls: Array<['info' | 'warn' | 'warnOnce' | 'error', string]> = [
      ['info', 'one'],
      ['error', viteLine(SEARCH, STACKS.refused)],
      ['warn', ''],
      ['error', viteLine(FACT, STACKS.hangUp)],
      ['warnOnce', 'two'],
      ['info', viteLine(SEARCH, STACKS.reset)],
      ['error', 'three'],
    ];
    for (const [method, msg] of calls) logger[method](msg);
    const total = base.info.mock.calls.length + base.warn.mock.calls.length + base.warnOnce.mock.calls.length + base.error.mock.calls.length;
    expect(total).toBe(calls.length);
    expect(base.warn.mock.calls[0][0]).toBe('');

    // Not a string, against the types: handed on as it came, never thrown on.
    const odd = { toString: () => 'odd' } as unknown as string;
    logger.info(odd);
    expect(base.info.mock.calls.at(-1)?.[0]).toBe(odd);
  });

  it('hands the rest of the logger through', () => {
    const { base, logger } = fakeLogger();
    const err = new Error('x');
    expect(logger.hasErrorLogged(err)).toBe(true);
    expect(base.hasErrorLogged).toHaveBeenCalledWith(err);
    logger.clearScreen('info');
    expect(base.clearScreen).toHaveBeenCalledWith('info');
    base.hasWarned = true;
    expect(logger.hasWarned).toBe(true);
    logger.hasWarned = false;
    expect(base.hasWarned).toBe(false);
  });
});

describe("over Vite's own logger", () => {
  function realLogger() {
    const out = { log: vi.fn(), warn: vi.fn(), error: vi.fn() };
    const logger = withoutProxyPaths(createLogger('info', { console: out as unknown as Console, allowClearScreen: false }));
    return { out, logger };
  }

  it('prints the line with its timestamp, the method and the stack, and remembers the error', () => {
    const { out, logger } = realLogger();
    const err = failedRequest('DELETE', STACKS.refused);
    logger.error(viteLine(FACT, STACKS.refused), { timestamp: true, error: err });
    expect(out.error).toHaveBeenCalledTimes(1);
    const printed = plain(out.error.mock.calls[0][0]);
    expect(printed).toMatch(/^\S.* \[vite\] http proxy error: DELETE \[path left out\]\nAggregateError \[ECONNREFUSED\]: /);
    for (const word of WORDS) expect(printed).not.toContain(word);
    expect(logger.hasErrorLogged(err)).toBe(true);
    expect(logger.hasWarned).toBe(true);
  });

  it('prints an info, a warn and an error line as they came, each to its own console method', () => {
    const { out, logger } = realLogger();
    logger.info('ready');
    logger.warn('careful');
    logger.error('broken');
    expect(out.log.mock.calls).toEqual([['ready']]);
    expect(out.warn.mock.calls).toEqual([['careful']]);
    expect(out.error.mock.calls).toEqual([['broken']]);
  });
});

describe('the dev server vite.config.ts builds', () => {
  const servers: Array<{ close: () => Promise<void> }> = [];
  const savedTarget = process.env.VITE_PROXY_TARGET;
  const tmpDirs: string[] = [];

  afterEach(async () => {
    vi.restoreAllMocks();
    while (servers.length) await servers.pop()!.close();
    while (tmpDirs.length) fs.rmSync(tmpDirs.pop()!, { recursive: true, force: true });
    if (savedTarget === undefined) delete process.env.VITE_PROXY_TARGET;
    else process.env.VITE_PROXY_TARGET = savedTarget;
  });

  async function closedPort() {
    const probe = net.createServer();
    await new Promise<void>((resolve) => probe.listen(0, '127.0.0.1', resolve));
    const { port } = probe.address() as net.AddressInfo;
    await new Promise((resolve) => probe.close(resolve));
    return port;
  }

  /** Starts the server, sends one search and one fact delete through its proxy, and returns all it printed. */
  async function printedFor(extra: InlineConfig = {}) {
    // vite.config.ts reads its target when createServer loads the file.
    process.env.VITE_PROXY_TARGET = `http://127.0.0.1:${await closedPort()}`;
    const printed: string[] = [];
    for (const method of ['log', 'info', 'warn', 'error', 'debug'] as const) {
      vi.spyOn(console, method).mockImplementation((...args: unknown[]) => {
        printed.push(args.map(String).join(' '));
      });
    }
    const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vite-proxy-log-'));
    tmpDirs.push(cacheDir);
    const server = await createServer({
      configFile: path.join(FRONTEND, 'vite.config.ts'),
      root: FRONTEND,
      // Never the node_modules/.vite a running dev server reads.
      cacheDir,
      optimizeDeps: { noDiscovery: true, include: [] },
      server: { host: '127.0.0.1', port: 0, watch: null },
      ...extra,
    });
    servers.push(server);
    await server.listen();
    const { port } = server.httpServer!.address() as net.AddressInfo;
    const statuses = [];
    for (const [method, url] of [['GET', SEARCH], ['DELETE', FACT]]) {
      const response = await fetch(`http://127.0.0.1:${port}${url}`, { method });
      statuses.push(response.status);
    }
    expect(statuses).toEqual([502, 502]);
    return plain(printed.join('\n'));
  }

  it('prints each failed request by its method and stack, and neither its words nor its path', async () => {
    const printed = await printedFor();
    expect(printed).toContain(`http proxy error: GET ${PATH_LEFT_OUT}\n`);
    expect(printed).toContain(`http proxy error: DELETE ${PATH_LEFT_OUT}\n`);
    expect(printed).toContain('ECONNREFUSED');
    expect(printed).not.toContain('/api/v1/');
    for (const word of WORDS) expect(printed).not.toContain(word);
  }, 60_000);

  it("would print both URLs whole with Vite's own logger in its place (the check sees a leak)", async () => {
    const printed = await printedFor({ customLogger: createLogger() });
    expect(printed).toContain(`http proxy error: ${SEARCH}\n`);
    expect(printed).toContain(`http proxy error: ${FACT}\n`);
  }, 60_000);
});
