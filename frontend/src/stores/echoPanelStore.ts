/**
 * The Echo panel's UI state (S-3.8.1): whether it is open, which mode, and
 * the conversation held in it this session. The panel is mounted once in
 * AppLayout, so the thread survives moving between pages; it is not stored
 * anywhere else, because every answer is already saved where it was asked
 * (library Q&A, Q&A history) and a draft by its own endpoint.
 */
import { create } from 'zustand';

export type EchoMode = 'ask' | 'draft';
export type AskTarget = 'library' | 'history';

export interface EchoTurn {
  id: string;
  kind: AskTarget | 'draft';
  /** What the user typed: a question, or the message to answer. */
  text: string;
  status: 'pending' | 'done' | 'error';
  /** The response body as the endpoint returned it. */
  result?: unknown;
  error?: string;
  /** A draft that names private people waits for the user to confirm them
   * (S-3.4.1's guard). */
  confirmNames?: string[];
}

interface EchoPanelStore {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
  mode: EchoMode;
  setMode: (mode: EchoMode) => void;
  target: AskTarget;
  setTarget: (target: AskTarget) => void;
  /** The Ask field's text: a card's question can be put there (S-3.8.2). */
  askText: string;
  setAskText: (text: string) => void;
  turns: EchoTurn[];
  addTurn: (turn: EchoTurn) => void;
  updateTurn: (id: string, patch: Partial<EchoTurn>) => void;
  clearTurns: () => void;
}

export const useEchoPanelStore = create<EchoPanelStore>((set, get) => ({
  open: false,
  setOpen: (open) => set({ open }),
  toggle: () => set({ open: !get().open }),
  mode: 'ask',
  setMode: (mode) => set({ mode }),
  target: 'library',
  setTarget: (target) => set({ target }),
  askText: '',
  setAskText: (askText) => set({ askText }),
  turns: [],
  addTurn: (turn) => set({ turns: [...get().turns, turn] }),
  updateTurn: (id, patch) => set({ turns: get().turns.map((t) => (t.id === id ? { ...t, ...patch } : t)) }),
  clearTurns: () => set({ turns: [] }),
}));
