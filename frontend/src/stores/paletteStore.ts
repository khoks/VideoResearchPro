/**
 * Command palette UI state (S-8.2.2): whether it is open, and whether the
 * single-key shortcuts (`/` and the `g` chords) are on.
 *
 * WCAG 2.1 SC 2.1.4 asks that a shortcut made of one printable key can be
 * turned off; the palette's own "Turn single-key shortcuts off" action is
 * that switch. The choice is per browser (guarded localStorage).
 */
import { create } from 'zustand';

const SINGLE_KEY = 'pratidhvani:single-key-shortcuts';

function loadSingleKey(): boolean {
  try {
    return window.localStorage.getItem(SINGLE_KEY) !== 'off';
  } catch {
    return true;
  }
}

interface PaletteStore {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
  singleKeyShortcuts: boolean;
  setSingleKeyShortcuts: (on: boolean) => void;
}

export const usePaletteStore = create<PaletteStore>((set, get) => ({
  open: false,
  setOpen: (open) => set({ open }),
  toggle: () => set({ open: !get().open }),
  singleKeyShortcuts: typeof window === 'undefined' ? true : loadSingleKey(),
  setSingleKeyShortcuts: (on) => {
    try {
      window.localStorage.setItem(SINGLE_KEY, on ? 'on' : 'off');
    } catch {
      /* storage unavailable: lasts for this page only */
    }
    set({ singleKeyShortcuts: on });
  },
}));
