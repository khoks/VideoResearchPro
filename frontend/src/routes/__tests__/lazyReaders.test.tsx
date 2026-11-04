/**
 * T-8.8.4.1: the three reader routes load their pages on demand, so the
 * sanitiser, the HTML parser and the remark-gfm / hast stack leave the
 * first-paint chunk.
 *
 * Checked on the router the app mounts: each reader route's element is a
 * Suspense boundary around a React.lazy page, with the reader's own loading
 * line as the fallback. The router module must not import the pages, or the
 * reader barrel, statically: either would put them back in the main chunk.
 */
import { isValidElement, Suspense, type ReactElement } from 'react';
import { describe, expect, it } from 'vitest';
import type { RouteObject } from 'react-router-dom';
import { router } from '../index';
import { ReaderLoading } from '../../components/reader/ReaderLoading';

const LAZY = Symbol.for('react.lazy');

function find(routes: RouteObject[], path: string): RouteObject | undefined {
  for (const r of routes) {
    if (r.path === path) return r;
    const hit = r.children ? find(r.children, path) : undefined;
    if (hit) return hit;
  }
  return undefined;
}

const READERS: Array<[string, string, string]> = [
  ['reports/:jobId', 'ReportReaderPage', 'Opening the report…'],
  ['knowledge/:videoId', 'KnowledgeReaderPage', 'Opening the knowledge report…'],
  ['author/outputs/:outputId', 'OutputReaderPage', 'Opening the manuscript…'],
];

describe('reader routes', () => {
  it.each(READERS)('%s renders a lazy page inside Suspense', async (path, page, loading) => {
    const route = find(router.routes as RouteObject[], path);
    expect(route, path).toBeDefined();
    const element = route!.element as ReactElement<{ fallback: ReactElement<{ label: string }>; children: ReactElement }>;
    expect(isValidElement(element)).toBe(true);
    expect(element.type).toBe(Suspense);

    const fallback = element.props.fallback;
    expect(fallback.type).toBe(ReaderLoading);
    expect(fallback.props.label).toBe(loading);

    const child = element.props.children;
    const lazyType = child.type as unknown as { $$typeof: symbol; _payload: unknown; _init: (p: unknown) => unknown };
    expect(lazyType.$$typeof).toBe(LAZY);

    // The lazy page resolves to the page component itself.
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

  it('keeps the readers and the reader barrel out of the router module’s static imports', () => {
    const source = Object.values(
      import.meta.glob('../index.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
    )[0];
    const staticImports = source.match(/^import [^;]+;$/gm) ?? [];
    for (const page of READERS.map(([, p]) => p)) {
      expect(staticImports.some((line) => line.includes(page)), page).toBe(false);
      expect(source).toContain(`import('../pages/${page}')`);
    }
    expect(staticImports.some((line) => /from '\.\.\/components\/reader'/.test(line))).toBe(false);
  });
});
