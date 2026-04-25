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
import { colors, type Mode, type ColorToken, shadow } from '../theme';

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
