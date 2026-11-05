/**
 * T-1.15.4.5: the answers of this session that stopped at their token budget.
 *
 * A fresh answer says so (`answer_cut_off`), but nothing stores that: it would
 * take a column on both exchange tables, and this was asked for without a
 * migration. Every ask refetches the history, which knows nothing of it, so the
 * cards read it from here, by exchange id. A reload forgets it, and the warning
 * in the server's log is what remains.
 */
import { create } from 'zustand';
import type { Depth } from '../utils/depth';

interface QACutOffState {
  /** Exchange id to the depth that ask carried, null when it carried none. */
  answers: Record<string, Depth | null>;
  note: (exchangeId: string, askedAt: Depth | null) => void;
}

export const useQACutOffStore = create<QACutOffState>((set) => ({
  answers: {},
  note: (exchangeId, askedAt) => set((s) => ({ answers: { ...s.answers, [exchangeId]: askedAt } })),
}));

/** Keep what a fresh answer said about itself. Call with the mutation's reply. */
export function rememberCutOff(
  exchange: { id: string; answer_cut_off?: boolean } | null | undefined,
  request: { output_length?: Depth },
): void {
  if (exchange?.answer_cut_off) useQACutOffStore.getState().note(exchange.id, request.output_length ?? null);
}
