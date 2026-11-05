import { create } from 'zustand';

export type LLMStatus = 'ok' | 'degraded' | 'down' | 'unknown';

/** A source that refused this install, from `/health` (T-1.5.14.1). */
export interface SourceHold {
  status: number;
  until: string;
}

interface SystemStatusState {
  llmStatus: LLMStatus;
  unavailableFeatures: string[];
  lastCheckedAt: number | null;
  /**
   * Install-level opt-in switches from `/health` `capabilities`
   * (e.g. `visual_analysis_enabled`, S-1.18.2). Null until the first poll.
   */
  capabilities: Record<string, boolean> | null;
  /** `/health` `source_holds`, by source type. Empty when nothing is on hold. */
  sourceHolds: Record<string, SourceHold>;
  setStatus: (status: LLMStatus, unavailableFeatures: string[], lastCheckedAt: number) => void;
  setCapabilities: (capabilities: Record<string, boolean>) => void;
  setSourceHolds: (sourceHolds: Record<string, SourceHold>) => void;
}

function arraysEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

function recordsEqual(a: Record<string, boolean> | null, b: Record<string, boolean>): boolean {
  if (!a) return false;
  const ka = Object.keys(a);
  return ka.length === Object.keys(b).length && ka.every((k) => a[k] === b[k]);
}

export const useSystemStatusStore = create<SystemStatusState>((set, get) => ({
  llmStatus: 'unknown',
  unavailableFeatures: [],
  lastCheckedAt: null,
  capabilities: null,
  sourceHolds: {},
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
  setCapabilities: (capabilities) => {
    if (recordsEqual(get().capabilities, capabilities)) return;
    set({ capabilities });
  },
  setSourceHolds: (sourceHolds) => {
    if (JSON.stringify(get().sourceHolds) === JSON.stringify(sourceHolds)) return;
    set({ sourceHolds });
  },
}));
