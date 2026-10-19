/**
 * The visible way into the palette (S-8.2.2): the shortcut is invisible to
 * new users and absent on touch screens. Full width with the shortcut hint
 * in the sidebar; an icon-sized 44 px target in the mobile bar.
 */
import { useState } from 'react';
import { modLabel } from '../../hooks/useShortcuts';
import { useColors } from '../../hooks/useTheme';
import { usePaletteStore } from '../../stores/paletteStore';
import { fonts, fontSize, radius, space, target } from '../../theme';

export function SearchButton({ compact = false }: { compact?: boolean }) {
  const c = useColors();
  const setOpen = usePaletteStore((s) => s.setOpen);
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      onClick={() => setOpen(true)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-haspopup="dialog"
      aria-label={compact ? 'Search and commands' : undefined}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: compact ? 'center' : 'space-between',
        gap: space['2'],
        width: compact ? target.primary : '100%',
        minHeight: compact ? target.primary : 36,
        padding: compact ? 0 : `0 ${space['3']}`,
        background: hover ? c.surfaceAlt : compact ? 'transparent' : c.bg,
        border: compact ? 'none' : `1px solid ${c.border}`,
        borderRadius: radius.md,
        color: c.textSecondary,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        cursor: 'pointer',
      }}
    >
      <span aria-hidden style={{ fontSize: compact ? fontSize.lg : fontSize.sm }}>⌕</span>
      {!compact && (
        <>
          <span style={{ flex: 1, textAlign: 'left' }}>Search…</span>
          <kbd style={{ fontFamily: fonts.mono, fontSize: fontSize.xs, color: c.textMuted }}>{modLabel()} K</kbd>
        </>
      )}
    </button>
  );
}
