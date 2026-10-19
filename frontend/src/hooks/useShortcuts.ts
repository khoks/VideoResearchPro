/**
 * Global keyboard shortcuts (S-8.2.2; the hook `ui-design.md` §2.1 describes).
 *
 * A binding is a chord (`mod+k`, `ctrl+alt+k`), a single key (`/`), or a
 * two-key sequence (`g r`, the second key within a second of the first).
 * `mod` is Cmd on macOS and Ctrl elsewhere: on macOS Ctrl-K is the text
 * fields' kill-line, so it stays theirs.
 *
 * Typing never triggers a shortcut: keys pressed in an input, textarea,
 * select or contenteditable are ignored unless the binding sets
 * `allowInInputs` (only the palette chords do). Single keys and sequences
 * are "character-key shortcuts" under WCAG 2.1 SC 2.1.4, so they carry
 * `singleKey: true` and the caller passes `singleKeyEnabled` from the
 * user's setting.
 */
import { useEffect, useRef } from 'react';

export interface Shortcut {
  /** `mod+k`, `ctrl+alt+k`, `/`, `escape`, or a sequence like `g r`. */
  keys: string;
  run: (event: KeyboardEvent) => void;
  allowInInputs?: boolean;
  /** A printable key with no modifier, or a sequence of them (SC 2.1.4). */
  singleKey?: boolean;
}

const SEQUENCE_WINDOW_MS = 1000;

export function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false;
  const p = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ?? navigator.platform ?? '';
  return /mac|iphone|ipad/i.test(p);
}

/** The key a shortcut label should name for `mod`. */
export function modLabel(mac = isMacPlatform()): string {
  return mac ? '⌘' : 'Ctrl';
}

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag === 'INPUT') {
    const type = (target as HTMLInputElement).type;
    return !['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file'].includes(type);
  }
  return false;
}

/** Whether a keydown event is exactly this chord (not a sequence). */
export function matchesChord(e: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey'>, chord: string, mac = isMacPlatform()): boolean {
  const parts = chord.toLowerCase().split('+');
  const key = parts.pop()!;
  const want = { ctrl: false, meta: false, alt: false, shift: false };
  for (const m of parts) {
    if (m === 'mod') want[mac ? 'meta' : 'ctrl'] = true;
    else if (m === 'ctrl') want.ctrl = true;
    else if (m === 'meta' || m === 'cmd') want.meta = true;
    else if (m === 'alt' || m === 'option') want.alt = true;
    else if (m === 'shift') want.shift = true;
  }
  if (e.ctrlKey !== want.ctrl || e.metaKey !== want.meta || e.altKey !== want.alt) return false;
  // Shift is implied for symbols on many layouts (`/` is unshifted, `?` is
  // shifted); only check it when the chord names it.
  if (want.shift && !e.shiftKey) return false;
  // Ctrl+Alt+K arrives as key "k" on most layouts, but as a dead or
  // composed character on some; fall back to the physical key via `code`.
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase();
  if (k === key) return true;
  const code = (e as KeyboardEvent).code;
  return typeof code === 'string' && key.length === 1 && code.toLowerCase() === `key${key}`;
}

export function useShortcuts(bindings: Shortcut[], { singleKeyEnabled = true }: { singleKeyEnabled?: boolean } = {}) {
  const ref = useRef({ bindings, singleKeyEnabled });
  ref.current = { bindings, singleKeyEnabled };
  const pending = useRef<{ key: string; at: number } | null>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.isComposing) return;
      const { bindings: list, singleKeyEnabled: singleOn } = ref.current;
      const editable = isEditableTarget(e.target);
      const now = Date.now();
      const prefix = pending.current && now - pending.current.at <= SEQUENCE_WINDOW_MS ? pending.current.key : null;
      pending.current = null;

      for (const b of list) {
        if (editable && !b.allowInInputs) continue;
        if (b.singleKey && !singleOn) continue;
        const seq = b.keys.trim().split(/\s+/);
        if (seq.length === 2) {
          if (e.ctrlKey || e.metaKey || e.altKey) continue;
          if (prefix === seq[0] && e.key.toLowerCase() === seq[1]) {
            e.preventDefault();
            b.run(e);
            return;
          }
          continue;
        }
        if (matchesChord(e, seq[0])) {
          e.preventDefault();
          b.run(e);
          return;
        }
      }

      // Remember a possible first key of a sequence.
      if (!editable && singleOn && !e.ctrlKey && !e.metaKey && !e.altKey && e.key.length === 1) {
        const k = e.key.toLowerCase();
        if (list.some((b) => b.singleKey && b.keys.trim().split(/\s+/)[0] === k && b.keys.includes(' '))) {
          pending.current = { key: k, at: now };
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);
}
