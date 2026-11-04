/**
 * T-8.8.4.5: the Markdown renderer is a separate chunk. The text is on the page
 * before the chunk arrives, in the elements the renderer writes, so nothing
 * jumps; a chunk that cannot load leaves that text in place; and no page can
 * pull the renderer back into the main chunk with a static import.
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const SOURCE = [
  '## Findings',
  '',
  'Prices **rose** in [the first year](https://example.org/a).',
  '',
  '- one',
  '- two',
].join('\n');

const BLOCKS = ['H2', 'P', 'UL', 'LI', 'LI'];

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.doUnmock('react-markdown');
  vi.resetModules();
});

async function show(element: ReactNode) {
  await act(async () => {
    root.render(element);
  });
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function blocks() {
  return [...container.querySelectorAll('h1,h2,h3,h4,h5,h6,p,ul,ol,li,pre')].map((el) => el.tagName);
}

describe('Markdown', () => {
  it('shows the text as plain blocks first, then the real render, in the same layout', async () => {
    let release!: () => void;
    const arrived = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.doMock('react-markdown', async () => {
      const actual = await vi.importActual<typeof import('react-markdown')>('react-markdown');
      await arrived;
      return actual;
    });
    const { Markdown } = await import('../Markdown');
    await show(<Markdown>{SOURCE}</Markdown>);

    // While the chunk is on its way: readable, no marks, no link yet.
    expect(container.textContent).toBe('FindingsPrices rose in the first year.onetwo');
    expect(container.querySelector('a')).toBeNull();
    expect(container.querySelector('strong')?.textContent).toBe('rose');
    expect(blocks()).toEqual(BLOCKS);

    release();
    await vi.waitFor(async () => {
      await settle();
      expect(container.querySelector('a')?.getAttribute('href')).toBe('https://example.org/a');
    });
    expect(container.querySelector('strong')?.textContent).toBe('rose');
    expect(blocks(), 'the same blocks, so nothing moves').toEqual(BLOCKS);
  });

  it('keeps the plain text if the chunk cannot load', async () => {
    vi.doMock('react-markdown', () => {
      throw new Error('Failed to fetch dynamically imported module');
    });
    const { Markdown } = await import('../Markdown');
    await show(<Markdown>{SOURCE}</Markdown>);
    await settle();
    expect(blocks()).toEqual(BLOCKS);
    expect(container.textContent).toContain('Prices rose in the first year.');
  });

  it('gives each call its own boundary, so an answer never suspends its page', async () => {
    const { Markdown } = await import('../Markdown');
    await show(
      <div>
        <h1>The page</h1>
        <Markdown>first answer</Markdown>
        <Markdown>second answer</Markdown>
      </div>,
    );
    expect(container.textContent).toBe('The pagefirst answersecond answer');
  });
});

describe('the main chunk stays free of the renderer', () => {
  const sources = import.meta.glob(['../../../**/*.{ts,tsx}', '!**/__tests__/**'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;

  it('imports react-markdown statically only from the reader, which is its own chunk', () => {
    const importers = Object.entries(sources)
      .filter(([, source]) => /^import [^;]*from 'react-markdown';/m.test(source))
      .map(([path]) => path);
    expect(importers).toEqual(['../../reader/parseMarkdown.tsx']);
  });

  it('loads it on demand from the one component the pages use', () => {
    expect(sources['../Markdown.tsx']).toContain("import('react-markdown')");
  });
});
