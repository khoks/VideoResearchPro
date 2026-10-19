import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ReaderToolbar } from '../ReaderToolbar';
import { readerScaleFor, useReaderStore } from '../../../stores/readerStore';
import { readerScale } from '../../../theme';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const OUTLINE = [
  { id: 'one', text: 'One', level: 2 as const },
  { id: 'two', text: 'Two', level: 3 as const },
];

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  // jsdom has no layout, so no scrollIntoView; the jump only needs it to exist.
  Element.prototype.scrollIntoView ??= function scrollIntoView() {};
  useReaderStore.setState({ step: readerScale.indexOf(1) });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  for (const id of ['one', 'two']) {
    const h = document.createElement('h2');
    h.id = id;
    h.tabIndex = -1;
    host.appendChild(h);
  }
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function mount(outline = OUTLINE) {
  const mountPoint = document.createElement('div');
  host.appendChild(mountPoint);
  root = createRoot(mountPoint);
  act(() => root.render(<ReaderToolbar outline={outline} activeId="two" progress={0.42} />));
}

function button(name: string): HTMLButtonElement {
  const b = [...document.querySelectorAll('button')].find(
    (x) => x.getAttribute('aria-label') === name || x.textContent === name,
  );
  if (!b) throw new Error(`no button ${name}`);
  return b as HTMLButtonElement;
}

describe('ReaderToolbar', () => {
  it('is a labelled toolbar of 44 px controls with the reading percentage', () => {
    mount();
    const bar = document.querySelector('[role="toolbar"]')!;
    expect(bar.getAttribute('aria-label')).toBe('Reading controls');
    for (const b of bar.querySelectorAll('button')) {
      expect((b as HTMLElement).style.minHeight).toBe('44px');
      expect((b as HTMLElement).style.minWidth).toBe('44px');
    }
    expect(bar.textContent).toContain('42%');
  });

  it('steps the text size and stops at both ends', () => {
    mount();
    const start = useReaderStore.getState().step;
    act(() => button('Larger text').click());
    expect(useReaderStore.getState().step).toBe(start + 1);
    for (let i = 0; i < 10; i++) act(() => button('Larger text').click());
    expect(useReaderStore.getState().step).toBe(readerScale.length - 1);
    expect(button('Larger text').disabled).toBe(true);
    for (let i = 0; i < 10; i++) act(() => button('Smaller text').click());
    expect(useReaderStore.getState().step).toBe(0);
    expect(button('Smaller text').disabled).toBe(true);
    expect(readerScaleFor(99)).toBe(readerScale[readerScale.length - 1]);
  });

  it('opens Contents as a dialog focused on the current section, and Escape returns focus', () => {
    mount();
    act(() => button('Contents').click());
    const dialog = document.querySelector('[role="dialog"]')!;
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement?.textContent).toBe('Two');
    expect(button('Contents').getAttribute('aria-expanded')).toBe('true');
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(button('Contents'));
  });

  it('jumping to a section closes the sheet and focuses the heading', async () => {
    mount();
    act(() => button('Contents').click());
    const link = [...document.querySelectorAll<HTMLAnchorElement>('[role="dialog"] a')].find((a) => a.textContent === 'One')!;
    await act(async () => {
      link.click();
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement?.id).toBe('one');
  });

  it('omits Contents when the document has no headings', () => {
    mount([]);
    expect([...document.querySelectorAll('button')].some((b) => b.textContent === 'Contents')).toBe(false);
  });
});

describe('readerStore persistence', () => {
  it('survives storage that throws', () => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error('blocked');
    };
    try {
      useReaderStore.setState({ step: 1 });
      expect(() => useReaderStore.getState().larger()).not.toThrow();
      expect(useReaderStore.getState().step).toBe(2);
    } finally {
      Storage.prototype.setItem = original;
    }
  });
});
