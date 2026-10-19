import type { CSSProperties, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { usePaletteColor } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';

export interface LabelPillProps {
  /** A label-palette NAME (`theme.ts` `PALETTE_COLORS`); unknown names render as `default`. */
  color: string;
  children: ReactNode;
  /** Makes the text a router link. Clicks never bubble to an enclosing card. */
  to?: string;
  title?: string;
  /** Renders a small × that calls back; the pill never removes anything itself. */
  onRemove?: () => void;
  removeLabel?: string;
  removeBusy?: boolean;
  style?: CSSProperties;
}

/**
 * A user-applied label (shelf, tag): a bordered pill in one of the ten
 * palette colours, the text always present — colour is a hint, never the
 * only signal (M1 plan, `ui-design.md` §1.1).
 */
export function LabelPill({
  color,
  children,
  to,
  title,
  onRemove,
  removeLabel = 'Remove',
  removeBusy,
  style,
}: LabelPillProps) {
  const p = usePaletteColor(color);
  const text = (
    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{children}</span>
  );
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: space['1'],
        padding: `2px ${space['2']}`,
        borderRadius: radius.pill,
        background: p.bg,
        color: p.fg,
        border: `1px solid ${p.fg}`,
        fontFamily: fonts.ui,
        fontSize: fontSize.xs,
        fontWeight: fontWeight.medium,
        lineHeight: 1.4,
        maxWidth: 260,
        ...style,
      }}
    >
      {to ? (
        <Link
          to={to}
          title={title}
          onClick={(e) => e.stopPropagation()}
          style={{ color: 'inherit', textDecoration: 'none', minWidth: 0, display: 'inline-flex' }}
        >
          {text}
        </Link>
      ) : (
        <span title={title} style={{ minWidth: 0, display: 'inline-flex' }}>
          {text}
        </span>
      )}
      {onRemove && (
        <button
          type="button"
          aria-label={removeLabel}
          disabled={removeBusy}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          style={{
            background: 'transparent',
            border: 'none',
            padding: 0,
            marginLeft: 2,
            color: 'inherit',
            cursor: removeBusy ? 'wait' : 'pointer',
            fontSize: fontSize.sm,
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </span>
  );
}
