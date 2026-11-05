/**
 * T-1.15.4.5: the depth a cut answer of this session was asked at.
 *
 * Whether an answer was cut is stored on the exchange and comes back with the
 * history (T-1.15.4.8). The depth is not stored, and `AnswerCutOffNote` needs it
 * to keep Deep from being offered to an answer already asked at Deep (D-145). A
 * reload forgets it, so the note stays and the offer goes.
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

/** Keep the depth of an ask whose answer was cut. Call with the mutation's reply. */
export function rememberCutOff(
  exchange: { id: string; answer_cut_off?: boolean } | null | undefined,
  request: { output_length?: Depth },
): void {
  if (exchange?.answer_cut_off) useQACutOffStore.getState().note(exchange.id, request.output_length ?? null);
}
