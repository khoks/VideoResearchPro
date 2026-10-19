/**
 * Where a hover card goes, given its anchor's rect (S-8.8.2).
 *
 * CSS anchor positioning is still partial across engines, so the card is
 * placed from `getBoundingClientRect()` in viewport coordinates (the card is
 * `position: fixed`, or in the top layer when the Popover API is there).
 * Below the anchor when it fits, above when it does not, centred on the
 * anchor and clamped inside the viewport either way.
 */
export interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface Placement {
  top: number;
  left: number;
  side: 'below' | 'above';
}

export function placeCard(
  anchor: Box,
  card: { width: number; height: number },
  viewport: { width: number; height: number },
  gap = 8,
  margin = 8,
): Placement {
  const below = anchor.top + anchor.height + gap;
  const above = anchor.top - gap - card.height;
  const fitsBelow = below + card.height <= viewport.height - margin;
  const fitsAbove = above >= margin;
  const side: Placement['side'] = fitsBelow || !fitsAbove ? 'below' : 'above';
  const rawTop = side === 'below' ? below : above;
  const top = Math.max(margin, Math.min(rawTop, viewport.height - card.height - margin));
  const centred = anchor.left + anchor.width / 2 - card.width / 2;
  const left = Math.max(margin, Math.min(centred, viewport.width - card.width - margin));
  return { top, left, side };
}
