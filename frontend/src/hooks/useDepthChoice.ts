/**
 * A page's depth control (R4 / D-064) that starts from somewhere (T-1.15.3.9):
 * the account's default depth, or a run's own depth in the knowledge drawer.
 *
 * `picked` stays undefined until the reader touches the control, so a preference
 * that arrives with `/auth/me`, after the first render, still fills it. Once
 * touched the pick stands, and that includes "Default" or "Auto", which is a pick
 * of no depth: a choice made on a page wins over the preference. `reset` goes
 * back to the start, for the panels where a pick is for one ask (D-125).
 */
import { useState } from 'react';
import type { Depth } from '../utils/depth';

export function useDepthChoice(start: Depth | null) {
  const [picked, setPicked] = useState<Depth | null | undefined>(undefined);
  return {
    depth: picked === undefined ? start : picked,
    pick: setPicked,
    reset: () => setPicked(undefined),
  };
}
