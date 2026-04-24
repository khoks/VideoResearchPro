import { create } from 'zustand';

export type LLMStatus = 'ok' | 'degraded' | 'down' | 'unknown';

interface SystemStatusState {
  llmStatus: LLMStatus;
  unavailableFeatures: string[];
  lastCheckedAt: number | null;
  setStatus: (status: LLMStatus, unavailableFeatures: string[], lastCheckedAt: number) => void;
}

function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

export const useSystemStatusStore = create<SystemStatusState>((set, get) => ({
  llmStatus: 'unknown',
  unavailableFeatures: [],
  lastCheckedAt: null,
  setStatus: (status, unavailableFeatures, lastCheckedAt) => {
    const prev = get();
    if (
      prev.llmStatus === status &&
      arraysEqual(prev.unavailableFeatures, unavailableFeatures)
    ) {
      // No meaningful change — still record the timestamp so consumers can tell
      // polling is alive, but don't churn the status/features references.
      set({ lastCheckedAt });
      return;
    }
    set({ llmStatus: status, unavailableFeatures, lastCheckedAt });
  },
}));
