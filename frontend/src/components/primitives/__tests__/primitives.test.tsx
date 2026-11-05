/**
 * T-2.2.2 to T-2.2.4: the primitives the pages' own copies moved into. The
 * styles are pinned because the move had to leave every page rendering as it
 * did, and the device baselines do not reach the tab bars.
 */
import { act, createRef } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IconButton, Tab, Tabs, ToastContainer } from '..';
import { useJobStore } from '../../../stores/jobStore';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  useJobStore.setState({ toasts: [] });
});

describe('Tabs', () => {
  it('is a labelled tab list on the shared underline', () => {
    act(() =>
      root.render(
        <Tabs label="Library sections">
          <Tab active onClick={() => undefined}>Sources</Tab>
          <Tab active={false} onClick={() => undefined}>Channels</Tab>
        </Tabs>,
      ),
    );
    const list = host.querySelector<HTMLElement>('[role="tablist"]')!;
    expect(list.getAttribute('aria-label')).toBe('Library sections');
    expect(list.style.display).toBe('flex');
    expect(list.style.marginBottom).toBe('1rem');
    expect(list.style.borderBottom).toContain('1px solid');

    const [on, off] = Array.from(host.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
    expect(on.getAttribute('aria-selected')).toBe('true');
    expect(off.getAttribute('aria-selected')).toBe('false');
    expect(on.type).toBe('button');
    expect(on.style.borderBottom).not.toContain('transparent');
    expect(off.style.borderBottom).toContain('transparent');
    expect(on.style.fontWeight).not.toBe(off.style.fontWeight);
    expect(on.style.letterSpacing).toBe('0.02em');
    expect(on.style.marginBottom).toBe('-1px');
  });

  it('lets a page keep its own spacing', () => {
    act(() =>
      root.render(
        <Tabs label="Research type" style={{ marginBottom: '1.5rem' }}>
          <Tab active onClick={() => undefined} style={{ letterSpacing: 'normal' }}>Topic</Tab>
        </Tabs>,
      ),
    );
    expect(host.querySelector<HTMLElement>('[role="tablist"]')!.style.marginBottom).toBe('1.5rem');
    expect(host.querySelector<HTMLElement>('[role="tab"]')!.style.letterSpacing).toBe('normal');
  });

  it('reports a click on a tab', () => {
    const onClick = vi.fn();
    act(() =>
      root.render(
        <Tabs label="x">
          <Tab active={false} onClick={onClick}>Other</Tab>
        </Tabs>,
      ),
    );
    act(() => host.querySelector<HTMLButtonElement>('[role="tab"]')!.click());
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe('IconButton', () => {
  it('takes its name from the label and sits bare on the surface', () => {
    act(() => root.render(<IconButton label="Remove tag">×</IconButton>));
    const b = host.querySelector('button')!;
    expect(b.getAttribute('aria-label')).toBe('Remove tag');
    expect(b.type).toBe('button');
    expect(b.style.background).toBe('transparent');
    expect(b.style.cursor).toBe('pointer');
    expect(b.style.getPropertyValue('border-style') || b.style.border).toContain('none');
  });

  it('passes through a ref, attributes and style, and the style wins', () => {
    const ref = createRef<HTMLButtonElement>();
    const onClick = vi.fn();
    act(() =>
      root.render(
        <IconButton
          ref={ref}
          label="Notifications"
          onClick={onClick}
          aria-expanded={false}
          data-echo-first=""
          style={{ background: 'rgb(1, 2, 3)', cursor: 'wait', width: 36 }}
        >
          <svg />
        </IconButton>,
      ),
    );
    const b = host.querySelector('button')!;
    expect(ref.current).toBe(b);
    expect(b.getAttribute('aria-expanded')).toBe('false');
    expect(b.hasAttribute('data-echo-first')).toBe(true);
    expect(b.style.background).toBe('rgb(1, 2, 3)');
    expect(b.style.cursor).toBe('wait');
    expect(b.style.width).toBe('36px');
    act(() => b.click());
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe('ToastContainer', () => {
  it('shows what the store holds, and Dismiss removes it', () => {
    act(() => root.render(<ToastContainer />));
    expect(host.textContent).toBe('');
    act(() => useJobStore.getState().pushToast('success', 'Added to Echo.'));
    expect(host.querySelector('[role="status"]')!.textContent).toContain('Added to Echo.');
    act(() => host.querySelector<HTMLButtonElement>('button[aria-label="Dismiss"]')!.click());
    expect(host.textContent).toBe('');
  });
});
