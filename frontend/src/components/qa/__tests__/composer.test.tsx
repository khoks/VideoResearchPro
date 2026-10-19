import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { DockedComposer, keyboardInset } from '../Composer';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('keyboardInset', () => {
  it('is the part of the layout viewport the visual viewport no longer shows', () => {
    expect(keyboardInset(800, { height: 800, offsetTop: 0, scale: 1 })).toBe(0);
    // Keyboard up, page not scrolled: 300 px hidden.
    expect(keyboardInset(800, { height: 500, offsetTop: 0, scale: 1 })).toBe(300);
    // iOS scrolls the visual viewport to keep the field visible.
    expect(keyboardInset(800, { height: 500, offsetTop: 120, scale: 1 })).toBe(180);
  });

  it('ignores pinch-zoom, which shrinks the visual viewport for another reason', () => {
    expect(keyboardInset(800, { height: 400, offsetTop: 0, scale: 2 })).toBe(0);
  });

  it('never goes negative', () => {
    expect(keyboardInset(800, { height: 820, offsetTop: 0, scale: 1 })).toBe(0);
  });
});

class FakeVisualViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
  scale = 1;
  width = 390;
  offsetLeft = 0;
  pageLeft = 0;
  pageTop = 0;
}

describe('DockedComposer', () => {
  let host: HTMLDivElement;
  let root: Root;
  let vv: FakeVisualViewport;
  const original = Object.getOwnPropertyDescriptor(window, 'visualViewport');

  beforeEach(() => {
    vv = new FakeVisualViewport();
    Object.defineProperty(window, 'visualViewport', { value: vv, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
    if (original) Object.defineProperty(window, 'visualViewport', original);
    else delete (window as { visualViewport?: unknown }).visualViewport;
  });

  it('lifts itself by the keyboard inset when the visual viewport shrinks', async () => {
    act(() => {
      root.render(
        <DockedComposer>
          <input aria-label="Question" />
        </DockedComposer>,
      );
    });
    const el = host.querySelector<HTMLElement>('.qa-composer')!;
    expect(el.style.getPropertyValue('--kb-inset')).toBe('0px');

    await act(async () => {
      vv.height = 460;
      vv.dispatchEvent(new Event('resize'));
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    });
    expect(el.style.getPropertyValue('--kb-inset')).toBe('340px');

    await act(async () => {
      vv.height = 800;
      vv.dispatchEvent(new Event('resize'));
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    });
    expect(el.style.getPropertyValue('--kb-inset')).toBe('0px');
  });
});
