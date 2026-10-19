/*
 * Theme-mode hook + resolved-color map for primitives.
 *
 * Primitives call `useColors()` to get the current-mode-resolved color object
 * (e.g. `c.bg` → '#faf6f0' in light, '#1c1814' in dark). The underlying mode
 * comes from `useJobStore.theme` which is already wired to `data-theme` on
 * <html> and to localStorage persistence.
 */

import { useMemo } from 'react';
import { useJobStore } from '../stores/jobStore';
import {
  chartColors,
  colors,
  isPaletteColor,
  palette,
  type ChartColorToken,
  type Mode,
  type ColorToken,
  shadow,
} from '../theme';

export type ResolvedColors = { [K in ColorToken]: string };

export function useThemeMode(): Mode {
  return useJobStore((s) => s.theme);
}

export function useColors(): ResolvedColors {
  const mode = useThemeMode();
  return useMemo(() => {
    const entries = (Object.keys(colors) as ColorToken[]).map((key) => [key, colors[key][mode]] as const);
    return Object.fromEntries(entries) as ResolvedColors;
  }, [mode]);
}

export function useShadows() {
  const mode = useThemeMode();
  return {
    none: shadow.none,
    hover: shadow.hover,
    floating: mode === 'dark' ? shadow.floatingDark : shadow.floating,
  };
}

/** Resolve a label-palette colour NAME (shelves, tags) for the current mode.
 * Unknown names fall back to `default` rather than rendering unstyled. */
export function usePaletteColor(name: string): { bg: string; fg: string } {
  const mode = useThemeMode();
  return palette[isPaletteColor(name) ? name : 'default'][mode];
}

/** Chart mark colours for the current mode (see `chartColors` in theme.ts). */
export function useChartColors(): Record<ChartColorToken, string> {
  const mode = useThemeMode();
  return useMemo(() => {
    const entries = (Object.keys(chartColors) as ChartColorToken[]).map((k) => [k, chartColors[k][mode]] as const);
    return Object.fromEntries(entries) as Record<ChartColorToken, string>;
  }, [mode]);
}
