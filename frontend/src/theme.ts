/*
 * Design tokens for Pratidhvani (प्रतिध्वनि).
 *
 * Source of truth: docs/ui-design.md (which itself mirrors docs/branding.md).
 *
 * Every inline style in the app reads values from here. Raw hex, magic spacings,
 * and ad-hoc font stacks are disallowed. If you need a new value, add it here
 * first — don't inline it.
 *
 * Light/dark resolution is driven by the `data-theme` attribute on <html>,
 * which `uiStore` toggles. Token lookups for colors use `pickColor(token, mode)`;
 * CSS variables in `index.css` mirror the same set for places where we can't
 * thread a mode prop (e.g. native `::placeholder` rules).
 */

export type Mode = 'light' | 'dark';

export type ColorToken = keyof typeof colors;

export const colors = {
  // Surface
  bg:           { light: '#faf6f0', dark: '#1c1814' },   // page paper
  surface:      { light: '#fffaf3', dark: '#252019' },   // raised card
  surfaceAlt:   { light: '#f0e9dd', dark: '#161310' },   // sunken / chip

  // Text
  textPrimary:  { light: '#1f1b16', dark: '#e8e2d6' },
  textSecondary:{ light: '#5c5448', dark: '#a89f93' },
  textMuted:    { light: '#7d756b', dark: '#7c7264' },
  textInverted: { light: '#faf6f0', dark: '#1c1814' },

  // Lines
  border:       { light: '#d8cfc0', dark: '#3a342b' },
  borderStrong: { light: '#bcae97', dark: '#544c3f' },

  // Accents
  accent:       { light: '#7a2c1a', dark: '#b04a2f' },   // oxblood
  accentSubtle: { light: '#f6e9e3', dark: '#3a1f17' },
  forest:       { light: '#2d4a3e', dark: '#5e8a78' },
  gold:         { light: '#c79945', dark: '#d8b15a' },

  // Status (warm-coherent — no bolted-on UI palette)
  success:      { light: '#2d4a3e', dark: '#5e8a78' },
  successSubtle:{ light: '#e4ece6', dark: '#1f2b25' },
  warn:         { light: '#c79945', dark: '#d8b15a' },
  warnSubtle:   { light: '#f7ecd4', dark: '#3a2f18' },
  error:        { light: '#7a2c1a', dark: '#b04a2f' },
  errorSubtle:  { light: '#f6e9e3', dark: '#3a1f17' },
  info:         { light: '#3d5a73', dark: '#7a96b0' },
  infoSubtle:   { light: '#e5ecf2', dark: '#1f2a35' },

  // Focus ring — always visible, always warm
  focus:        { light: '#7a2c1a', dark: '#d8b15a' },
} as const;

export const fonts = {
  display:    '"Fraunces", Georgia, serif',
  body:       '"Source Serif Pro", "Fraunces", Georgia, serif',
  ui:         '"Inter", system-ui, -apple-system, sans-serif',
  devanagari: '"Tiro Devanagari Hindi", "Noto Serif Devanagari", serif',
  mono:       '"JetBrains Mono", ui-monospace, "Cascadia Code", monospace',
} as const;

export const fontSize = {
  xs:    '0.75rem',   // 12 — captions, micro-labels
  sm:    '0.875rem',  // 14 — secondary UI
  base:  '1rem',      // 16 — body
  md:    '1.125rem',  // 18 — comfortable reading
  lg:    '1.25rem',   // 20 — section headings
  xl:    '1.5rem',    // 24 — page section headers
  '2xl': '2rem',      // 32 — page titles
  '3xl': '2.75rem',   // 44 — hero, masthead
} as const;

export const lineHeight = {
  tight:  1.2,
  snug:   1.4,
  normal: 1.55,
  loose:  1.7,
} as const;

export const fontWeight = {
  regular:  400,
  medium:   500,
  semibold: 600,
  bold:     700,
} as const;

/** 4 px scale. No magic values outside this list. */
export const space = {
  '0':  0,
  '1':  '0.25rem',  // 4
  '2':  '0.5rem',   // 8
  '3':  '0.75rem',  // 12
  '4':  '1rem',     // 16
  '5':  '1.5rem',   // 24
  '6':  '2rem',     // 32
  '7':  '2.5rem',   // 40
  '8':  '3rem',     // 48
  '10': '4rem',     // 64
  '12': '6rem',     // 96
} as const;

export const radius = {
  none: 0,
  sm:   '4px',
  md:   '6px',
  lg:   '10px',
  pill: '999px',
} as const;

export const shadow = {
  none:     'none',
  hover:    '0 1px 2px rgba(31, 27, 22, 0.06)',
  floating: '0 8px 24px rgba(31, 27, 22, 0.18)',
  floatingDark: '0 8px 24px rgba(0, 0, 0, 0.4)',
} as const;

export const motion = {
  duration: { fast: 120, base: 200, slow: 320 },
  easing:   { standard: 'cubic-bezier(0.2, 0.8, 0.2, 1)' },
} as const;

export const z = {
  base:    0,
  content: 1,
  sticky:  100,
  drawer:  200,
  modal:   300,
  toast:   400,
  tooltip: 500,
  debug:   999,
} as const;

export const breakpoints = {
  mobile:  '640px',
  tablet:  '960px',
  desktop: '1200px',
} as const;

export const measure = {
  reading: '75ch',
  grid:    '1200px',
  form:    '560px',
} as const;

/** Resolve a color token for the given mode. Prefer `useColors()` in components. */
export function pickColor(token: ColorToken, mode: Mode): string {
  return colors[token][mode];
}

/** Convenience transition string. Usage: `transition: transitionAll('fast')`. */
export function transitionAll(d: keyof typeof motion.duration = 'fast'): string {
  return `all ${motion.duration[d]}ms ${motion.easing.standard}`;
}

/** Focus ring style — reuse on every interactive primitive. Never `outline:none` without this. */
export function focusRing(mode: Mode) {
  return {
    outline: `2px solid ${colors.focus[mode]}`,
    outlineOffset: '2px',
  } as const;
}
