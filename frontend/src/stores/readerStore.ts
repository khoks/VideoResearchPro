/**
 * Reader UI state (S-8.12.1): the text-size step chosen from the reading
 * toolbar on small screens. UI state lives in Zustand (ui-design §3); the
 * choice is a per-browser convenience, so it persists in localStorage and
 * every read and write is guarded — private windows and blocked storage
 * must still render the reader at the default size.
 */
import { create } from 'zustand';
import { readerScale } from '../theme';

const KEY = 'pratidhvani:reader-scale';
const DEFAULT_STEP = readerScale.indexOf(1);

function load(): number {
  try {
    const raw = window.localStorage.getItem(KEY);
    const n = raw == null ? NaN : Number(raw);
    return Number.isInteger(n) && n >= 0 && n < readerScale.length ? n : DEFAULT_STEP;
  } catch {
    return DEFAULT_STEP;
  }
}

function save(step: number) {
  try {
    window.localStorage.setItem(KEY, String(step));
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
}

interface ReaderStore {
  step: number;
  smaller: () => void;
  larger: () => void;
}

export const useReaderStore = create<ReaderStore>((set, get) => ({
  step: typeof window === 'undefined' ? DEFAULT_STEP : load(),
  smaller: () => {
    const step = Math.max(0, get().step - 1);
    save(step);
    set({ step });
  },
  larger: () => {
    const step = Math.min(readerScale.length - 1, get().step + 1);
    save(step);
    set({ step });
  },
}));

export function readerScaleFor(step: number): number {
  return readerScale[Math.max(0, Math.min(readerScale.length - 1, step))];
}
