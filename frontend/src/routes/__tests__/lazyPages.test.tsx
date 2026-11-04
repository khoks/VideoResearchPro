/**
 * T-8.8.4.5: pages an account opens now and then are their own chunks. Checked
 * on the router the app mounts: each is a lazy page inside Suspense, with a
 * loading line and the error screen a lazy route needs (a chunk can fail to
 * load where an eager page cannot). Importing one statically in the router
 * would put it back in the main chunk, whatever the route says.
 */
import { isValidElement, Suspense, type ReactElement } from 'react';
import { describe, expect, it } from 'vitest';
import type { RouteObject } from 'react-router-dom';
import { router } from '../index';
import { RouteLoadError } from '../../components/common/RouteLoadError';
import { Spinner } from '../../components/primitives';

const LAZY = Symbol.for('react.lazy');

const PAGES: Array<[string, string]> = [
  ['echo', 'EchoPage'],
  ['echo/inbox', 'EchoInboxPage'],
  ['echo/import', 'EchoImportPage'],
  ['author', 'AuthorPage'],
  ['account/subscription', 'SubscriptionPage'],
  ['account/ai-models', 'AIModelsPage'],
  ['account/system', 'SystemStatusPage'],
];

function find(routes: RouteObject[], path: string): RouteObject | undefined {
  for (const r of routes) {
    if (r.path === path) return r;
    const hit = r.children ? find(r.children, path) : undefined;
    if (hit) return hit;
  }
  return undefined;
}

describe('pages loaded on demand', () => {
  it.each(PAGES)('%s is a lazy page with a loading line and an error screen', async (path, page) => {
    const route = find(router.routes as RouteObject[], path);
    expect(route, path).toBeDefined();
    const element = route!.element as ReactElement<{ fallback: ReactElement<{ label: string }>; children: ReactElement }>;
    expect(isValidElement(element)).toBe(true);
    expect(element.type).toBe(Suspense);
    expect(element.props.fallback.type).toBe(Spinner);
    expect(element.props.fallback.props.label).toMatch(/^Loading /);
    expect((route!.errorElement as ReactElement).type).toBe(RouteLoadError);

    const lazyType = element.props.children.type as unknown as { $$typeof: symbol; _payload: unknown; _init: (p: unknown) => unknown };
    expect(lazyType.$$typeof).toBe(LAZY);
    const mod = await import(`../../pages/${page}.tsx`);
    let resolved: unknown;
    try {
      resolved = lazyType._init(lazyType._payload);
    } catch (pending) {
      await pending;
      resolved = lazyType._init(lazyType._payload);
    }
    expect(resolved).toBe(mod[page]);
  });

  it('keeps them out of the router module’s static imports', () => {
    const source = Object.values(
      import.meta.glob('../index.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
    )[0];
    const staticImports = source.match(/^import [^;]+;$/gm) ?? [];
    for (const [, page] of PAGES) {
      expect(staticImports.some((line) => line.includes(`/${page}'`)), page).toBe(false);
      expect(source).toContain(`import('../pages/${page}')`);
    }
  });
});
