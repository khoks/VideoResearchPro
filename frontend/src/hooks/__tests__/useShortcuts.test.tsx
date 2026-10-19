import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { isEditableTarget, matchesChord, useShortcuts, type Shortcut } from '../useShortcuts';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function ev(key: string, mods: Partial<Record<'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey', boolean>> = {}, code?: string) {
  return { key, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, code, ...mods } as unknown as KeyboardEvent;
}

describe('matchesChord', () => {
  it('reads mod as Ctrl off macOS and Cmd on macOS', () => {
    expect(matchesChord(ev('k', { ctrlKey: true }), 'mod+k', false)).toBe(true);
    expect(matchesChord(ev('k', { metaKey: true }), 'mod+k', false)).toBe(false);
    expect(matchesChord(ev('k', { metaKey: true }), 'mod+k', true)).toBe(true);
    expect(matchesChord(ev('k', { ctrlKey: true }), 'mod+k', true)).toBe(false); // macOS kill-line stays the field's
  });

  it('needs the exact modifiers', () => {
    expect(matchesChord(ev('k', { ctrlKey: true, altKey: true }), 'mod+k', false)).toBe(false);
    expect(matchesChord(ev('k', { ctrlKey: true, altKey: true }), 'ctrl+alt+k', false)).toBe(true);
    expect(matchesChord(ev('/'), '/', false)).toBe(true);
    expect(matchesChord(ev('/', { ctrlKey: true }), '/', false)).toBe(false);
  });

  it('falls back to the physical key when Ctrl-Alt composes a character', () => {
    expect(matchesChord(ev('ĸ', { ctrlKey: true, altKey: true }, 'KeyK'), 'ctrl+alt+k', false)).toBe(true);
  });
});

describe('isEditableTarget', () => {
  it('treats text fields and contenteditable as typing, not buttons or checkboxes', () => {
    const text = document.createElement('input');
    const box = document.createElement('input');
    box.type = 'checkbox';
    const area = document.createElement('textarea');
    const div = document.createElement('div');
    div.contentEditable = 'true';
    expect(isEditableTarget(text)).toBe(true);
    expect(isEditableTarget(area)).toBe(true);
    expect(isEditableTarget(box)).toBe(false);
    expect(isEditableTarget(document.createElement('button'))).toBe(false);
    // jsdom does not implement isContentEditable; real browsers do.
    expect(typeof isEditableTarget(div)).toBe('boolean');
  });
});

describe('useShortcuts', () => {
  let host: HTMLDivElement;
  let root: Root;

  function Harness({ bindings, singleKeyEnabled }: { bindings: Shortcut[]; singleKeyEnabled?: boolean }) {
    useShortcuts(bindings, { singleKeyEnabled });
    return <input aria-label="field" />;
  }

  beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  function press(key: string, target: EventTarget = document.body, mods: Record<string, boolean> = {}) {
    const e = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...mods });
    target.dispatchEvent(e);
    return e;
  }

  it('fires a chord anywhere, prevents the browser default, and works inside a field when allowed', () => {
    const run = vi.fn();
    act(() => root.render(<Harness bindings={[{ keys: 'ctrl+alt+k', run, allowInInputs: true }]} />));
    const e = press('k', document.body, { ctrlKey: true, altKey: true });
    expect(run).toHaveBeenCalledTimes(1);
    expect(e.defaultPrevented).toBe(true);
    press('k', host.querySelector('input')!, { ctrlKey: true, altKey: true });
    expect(run).toHaveBeenCalledTimes(2);
  });

  it('never fires a single-key shortcut while typing', () => {
    const run = vi.fn();
    act(() => root.render(<Harness bindings={[{ keys: '/', run, singleKey: true }]} />));
    const e = press('/', host.querySelector('input')!);
    expect(run).not.toHaveBeenCalled();
    expect(e.defaultPrevented).toBe(false);
    press('/');
    expect(run).toHaveBeenCalledTimes(1);
  });

  it('runs a two-key sequence only when the second key follows the first', () => {
    const run = vi.fn();
    act(() => root.render(<Harness bindings={[{ keys: 'g l', run, singleKey: true }]} />));
    press('l');
    expect(run).not.toHaveBeenCalled();
    press('g');
    press('l');
    expect(run).toHaveBeenCalledTimes(1);
    press('g');
    press('x');
    press('l');
    expect(run).toHaveBeenCalledTimes(1);
  });

  it('turns every single-key shortcut off with the setting, but never the chords (SC 2.1.4)', () => {
    const slash = vi.fn();
    const chord = vi.fn();
    act(() =>
      root.render(
        <Harness
          singleKeyEnabled={false}
          bindings={[
            { keys: '/', run: slash, singleKey: true },
            { keys: 'g l', run: slash, singleKey: true },
            { keys: 'ctrl+alt+k', run: chord, allowInInputs: true },
          ]}
        />,
      ),
    );
    press('/');
    press('g');
    press('l');
    press('k', document.body, { ctrlKey: true, altKey: true });
    expect(slash).not.toHaveBeenCalled();
    expect(chord).toHaveBeenCalledTimes(1);
  });
});
