import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, space } from '../../theme';

/** The table view every chart offers: the same numbers, no colour, no
 * hover needed (dataviz: tooltips enhance, they never gate). */
export function ChartTable({
  caption,
  columns,
  rows,
}: {
  caption: string;
  columns: string[];
  rows: (string | number)[][];
}) {
  const c = useColors();
  const cell = {
    padding: `${space['1']} ${space['2']}`,
    borderBottom: `1px solid ${c.border}`,
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    color: c.textPrimary,
    textAlign: 'left' as const,
  };
  return (
    <div style={{ maxHeight: 280, overflowY: 'auto', marginTop: space['2'] }}>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <caption
          style={{
            textAlign: 'left',
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            color: c.textMuted,
            paddingBottom: space['1'],
          }}
        >
          {caption}
        </caption>
        <thead>
          <tr>
            {columns.map((col, i) => (
              <th
                key={col}
                scope="col"
                style={{ ...cell, fontWeight: fontWeight.semibold, color: c.textSecondary, textAlign: i === 0 ? 'left' : 'right' }}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              {row.map((value, i) =>
                i === 0 ? (
                  <th key={i} scope="row" style={{ ...cell, fontWeight: fontWeight.regular }}>
                    {value}
                  </th>
                ) : (
                  <td key={i} style={{ ...cell, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {value}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
