import { useState, type ReactNode } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, space } from '../../theme';

export interface BarListRow {
  key: string;
  label: string;
  value: number;
  /** Shown when the row is opened (drill-down); omit for a plain row. */
  detail?: ReactNode;
}

/**
 * Ranked horizontal bars with the value at the tip: real text, one colour,
 * thin (8px) marks with a rounded data-end and a square baseline. Rows with
 * `detail` open in place (a button with `aria-expanded`). The numbers are in
 * the text, so no hover or table is needed to read them.
 */
export function BarList({
  rows,
  color,
  unit,
  labelWidth = '42%',
}: {
  rows: BarListRow[];
  color: string;
  unit: string;
  labelWidth?: string;
}) {
  const c = useColors();
  const [open, setOpen] = useState<string | null>(null);
  const max = Math.max(1, ...rows.map((r) => r.value));

  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: space['1'] }}>
      {rows.map((row) => {
        const isOpen = open === row.key;
        const body = (
          <span style={{ display: 'flex', alignItems: 'center', gap: space['2'], width: '100%' }}>
            <span
              style={{
                flex: `0 0 ${labelWidth}`,
                minWidth: 0,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                color: c.textPrimary,
                textAlign: 'left',
              }}
              title={row.label}
            >
              {row.detail ? (isOpen ? '▾ ' : '▸ ') : ''}
              {row.label}
            </span>
            <span style={{ flex: 1, display: 'flex', alignItems: 'center', gap: space['2'], minWidth: 0 }}>
              <span
                aria-hidden
                style={{
                  display: 'inline-block',
                  height: 8,
                  width: `${Math.max(2, (row.value / max) * 100)}%`,
                  maxWidth: 'calc(100% - 3rem)',
                  background: row.value > 0 ? color : 'transparent',
                  borderRadius: '0 4px 4px 0',
                }}
              />
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                {row.value}
                <span style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}> {unit}</span>
              </span>
            </span>
          </span>
        );
        return (
          <li key={row.key}>
            {row.detail ? (
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : row.key)}
                style={{ display: 'block', width: '100%', background: 'transparent', border: 'none', padding: `2px 0`, cursor: 'pointer' }}
              >
                {body}
              </button>
            ) : (
              <div style={{ padding: '2px 0' }}>{body}</div>
            )}
            {isOpen && row.detail && (
              <div style={{ padding: `${space['1']} 0 ${space['2']} ${space['4']}`, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, fontWeight: fontWeight.regular }}>
                {row.detail}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
