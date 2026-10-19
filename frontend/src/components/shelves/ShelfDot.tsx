import type { CSSProperties } from 'react';
import { usePaletteColor } from '../../hooks/useTheme';

/** A small colour marker for a shelf. Decorative: the name always sits next to it. */
export function ShelfDot({ color, size = 10, style }: { color: string; size?: number; style?: CSSProperties }) {
  const p = usePaletteColor(color);
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        borderRadius: '50%',
        background: p.bg,
        border: `1.5px solid ${p.fg}`,
        flexShrink: 0,
        ...style,
      }}
    />
  );
}
