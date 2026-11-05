/**
 * T-2.2.2 to T-2.2.4: the primitives the pages' own copies moved into. The
 * styles are pinned because the move had to leave every page rendering as it
 * did, and the device baselines do not reach the tab bars.
 *
 * T-2.2.5: the ARIA tabs keyboard on `Tabs`. Mutation checks, run by hand on
 * 2026-11-05: `tabIndex` left off fails "is one stop"; the wrap taken out fails
 * "wraps"; `preventDefault` gone fails "keeps the page still"; the modifier check gone
 * fails "leaves a modifier to the browser"; `next.click()` gone fails "opens".
 */
import { act, createRef, useState } from 'react';
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

describe('Tabs keyboard', () => {
  function Row({ onPick }: { onPick: (name: string) => void }) {
    const [active, setActive] = useState('Sources');
    return (
      <Tabs label="Library sections">
        {['Sources', 'Channels', 'Add'].map((name) => (
          <Tab
            key={name}
            active={active === name}
            onClick={() => {
              setActive(name);
              onPick(name);
            }}
          >
            {name}
          </Tab>
        ))}
      </Tabs>
    );
  }

  const tabs = () => Array.from(host.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
  const named = (name: string) => tabs().find((t) => t.textContent === name)!;
  const press = (key: string, init: KeyboardEventInit = {}) => {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
    act(() => {
      (document.activeElement as HTMLElement).dispatchEvent(event);
    });
    return event;
  };
  const start = (from = 'Sources') => {
    const onPick = vi.fn();
    act(() => root.render(<Row onPick={onPick} />));
    act(() => named('Sources').click());
    if (from !== 'Sources') act(() => named(from).click());
    onPick.mockClear();
    act(() => named(from).focus());
    return onPick;
  };

  it('is one stop for the Tab key, on the active tab', () => {
    start('Channels');
    expect(tabs().map((t) => t.tabIndex)).toEqual([-1, 0, -1]);
  });

  it('opens the next and the previous tab with the arrows, and focus goes along', () => {
    const onPick = start();
    press('ArrowRight');
    expect(onPick).toHaveBeenLastCalledWith('Channels');
    expect(document.activeElement).toBe(named('Channels'));
    expect(named('Channels').getAttribute('aria-selected')).toBe('true');
    expect(tabs().map((t) => t.tabIndex)).toEqual([-1, 0, -1]);
    press('ArrowLeft');
    expect(onPick).toHaveBeenLastCalledWith('Sources');
    expect(document.activeElement).toBe(named('Sources'));
  });

  it('wraps at both ends', () => {
    const onPick = start();
    press('ArrowLeft');
    expect(onPick).toHaveBeenLastCalledWith('Add');
    press('ArrowRight');
    expect(onPick).toHaveBeenLastCalledWith('Sources');
  });

  it('goes to the ends with Home and End', () => {
    const onPick = start('Channels');
    press('End');
    expect(onPick).toHaveBeenLastCalledWith('Add');
    expect(document.activeElement).toBe(named('Add'));
    press('Home');
    expect(onPick).toHaveBeenLastCalledWith('Sources');
    expect(document.activeElement).toBe(named('Sources'));
  });

  it('keeps the page still for the keys it uses, and only those', () => {
    start();
    expect(press('End').defaultPrevented).toBe(true);
    expect(press('Home').defaultPrevented).toBe(true);
    expect(press('ArrowDown').defaultPrevented).toBe(false);
    expect(press('Enter').defaultPrevented).toBe(false);
  });

  it.each([{ altKey: true }, { ctrlKey: true }, { metaKey: true }, { shiftKey: true }])('leaves a modifier to the browser: %j', (mod) => {
    const onPick = start();
    const event = press('ArrowRight', mod);
    expect(onPick).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(named('Sources'));
  });
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
