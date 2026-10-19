import { useId, useMemo, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';
import { useElementWidth } from './useElementWidth';
import { ChartTable } from './ChartTable';

export interface ColumnSeries {
  key: string;
  label: string;
  color: string;
}

export interface ColumnRow {
  key: string;
  /** Shown in the tooltip and the table. */
  label: string;
  values: Record<string, number>;
}

interface Props {
  /** Names the chart for assistive tech and the table caption. */
  title: string;
  rows: ColumnRow[];
  /** One series → plain columns, no legend; several → stacked, with a legend. */
  series: ColumnSeries[];
  /** Unit for the tooltip and table, e.g. "documents". */
  unit: string;
  /** X-axis label for a row, or null to leave that slot unlabelled. */
  xLabel?: (row: ColumnRow, index: number) => string | null;
  height?: number;
}

const MARGIN = { top: 8, right: 4, bottom: 22, left: 30 };
const GAP = 2; // surface gap between touching marks
const MAX_BAR = 24;
const CORNER = 4;

function niceMax(v: number): number {
  if (v <= 4) return Math.max(1, Math.ceil(v));
  const exp = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (m * exp >= v) return m * exp;
  }
  return 10 * exp;
}

/** A bar path with a rounded data-end and a square baseline. */
function columnPath(x: number, y: number, w: number, h: number, rounded: boolean): string {
  if (h <= 0) return '';
  const r = rounded ? Math.min(CORNER, w / 2, h) : 0;
  return [
    `M${x},${y + h}`,
    `V${y + r}`,
    r ? `Q${x},${y} ${x + r},${y}` : '',
    `H${x + w - r}`,
    r ? `Q${x + w},${y} ${x + w},${y + r}` : '',
    `V${y + h}`,
    'Z',
  ].join(' ');
}

/**
 * Columns over an ordered axis (months), single or stacked. Thin marks with a
 * rounded data-end, 2px surface gaps, hairline grid, a per-column tooltip on
 * hover and on keyboard (focus the chart, then ←/→), and a table view.
 */
export function ColumnChart({ title, rows, series, unit, xLabel, height = 180 }: Props) {
  const c = useColors();
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const descId = useId();

  const totals = useMemo(
    () => rows.map((r) => series.reduce((sum, s) => sum + (r.values[s.key] ?? 0), 0)),
    [rows, series],
  );
  const yMax = niceMax(Math.max(0, ...totals));
  const plotW = Math.max(0, width - MARGIN.left - MARGIN.right);
  const plotH = height - MARGIN.top - MARGIN.bottom;
  const slot = rows.length ? plotW / rows.length : 0;
  const barW = Math.max(1, Math.min(MAX_BAR, slot - GAP));
  const y = (v: number) => MARGIN.top + plotH - (v / yMax) * plotH;
  const ticks = [0, yMax / 2, yMax].filter((t, i, a) => a.indexOf(t) === i && Number.isInteger(t));

  const pick = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const i = Math.floor((e.clientX - box.left - MARGIN.left) / slot);
    setActive(i >= 0 && i < rows.length ? i : null);
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (!rows.length) return;
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      const step = e.key === 'ArrowRight' ? 1 : -1;
      setActive((a) => Math.min(rows.length - 1, Math.max(0, (a ?? (step > 0 ? -1 : rows.length)) + step)));
    } else if (e.key === 'Home') {
      setActive(0);
    } else if (e.key === 'End') {
      setActive(rows.length - 1);
    } else if (e.key === 'Escape') {
      setActive(null);
    }
  };

  const activeRow = active !== null ? rows[active] : null;
  const tipLeft = active !== null ? MARGIN.left + active * slot + slot / 2 : 0;
  const total = totals.reduce((a, b) => a + b, 0);
  const summary = `${title}: ${rows.length} columns, ${total} ${unit} in all, the most in one column ${Math.max(0, ...totals)}.`;

  return (
    <div>
      {series.length > 1 && (
        <ul
          aria-label="Legend"
          style={{ listStyle: 'none', margin: `0 0 ${space['2']}`, padding: 0, display: 'flex', flexWrap: 'wrap', gap: space['3'] }}
        >
          {series.map((s) => (
            <li key={s.key} style={{ display: 'inline-flex', alignItems: 'center', gap: space['1'], fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary }}>
              <span aria-hidden style={{ width: 10, height: 10, borderRadius: 2, background: s.color, display: 'inline-block' }} />
              {s.label}
            </li>
          ))}
        </ul>
      )}
      <div ref={ref} style={{ position: 'relative', width: '100%' }}>
        {width > 0 && (
          <svg
            width={width}
            height={height}
            role="group"
            aria-label={`${title}. Use left and right arrows to read each column.`}
            aria-describedby={descId}
            tabIndex={0}
            onPointerMove={pick}
            onPointerLeave={() => setActive(null)}
            onKeyDown={onKey}
            onBlur={() => setActive(null)}
            style={{ display: 'block', outline: 'none', borderRadius: radius.sm }}
            onFocus={(e) => {
              e.currentTarget.style.outline = `2px solid ${c.focus}`;
              e.currentTarget.style.outlineOffset = '2px';
            }}
            onBlurCapture={(e) => {
              e.currentTarget.style.outline = 'none';
            }}
          >
            {ticks.map((t) => (
              <g key={t}>
                <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(t)} y2={y(t)} stroke={c.border} strokeWidth={1} />
                <text x={MARGIN.left - 6} y={y(t)} dy="0.32em" textAnchor="end" fill={c.textMuted} fontFamily={fonts.ui} fontSize={10}>
                  {t}
                </text>
              </g>
            ))}
            {rows.map((row, i) => {
              const x = MARGIN.left + i * slot + (slot - barW) / 2;
              let base = 0;
              const present = series.filter((s) => (row.values[s.key] ?? 0) > 0);
              return (
                <g key={row.key} opacity={active === null || active === i ? 1 : 0.55}>
                  {present.map((s, k) => {
                    const v = row.values[s.key] ?? 0;
                    const top = y(base + v);
                    const bottom = y(base);
                    base += v;
                    const isTop = k === present.length - 1;
                    // The surface gap sits under every segment but the lowest.
                    const h = bottom - top - (k > 0 ? GAP : 0);
                    return <path key={s.key} d={columnPath(x, top, barW, Math.max(0, h), isTop)} fill={s.color} />;
                  })}
                  {xLabel && xLabel(row, i) && (
                    <text x={x + barW / 2} y={height - 6} textAnchor="middle" fill={c.textMuted} fontFamily={fonts.ui} fontSize={10}>
                      {xLabel(row, i)}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        )}
        {activeRow && (
          <div
            role="status"
            style={{
              position: 'absolute',
              top: 0,
              left: Math.min(Math.max(tipLeft, 70), Math.max(70, width - 70)),
              transform: 'translateX(-50%)',
              background: c.surface,
              border: `1px solid ${c.borderStrong}`,
              borderRadius: radius.sm,
              padding: `${space['1']} ${space['2']}`,
              fontFamily: fonts.ui,
              fontSize: fontSize.xs,
              color: c.textSecondary,
              pointerEvents: 'none',
              whiteSpace: 'nowrap',
              zIndex: 1,
            }}
          >
            <div style={{ color: c.textMuted }}>{activeRow.label}</div>
            {series.map((s) => (
              <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: space['1'] }}>
                {series.length > 1 && <span aria-hidden style={{ width: 10, height: 2, background: s.color, display: 'inline-block' }} />}
                <strong style={{ color: c.textPrimary, fontWeight: fontWeight.semibold }}>{activeRow.values[s.key] ?? 0}</strong>
                <span>{series.length > 1 ? s.label : (activeRow.values[s.key] ?? 0) === 1 ? unit.replace(/s$/, '') : unit}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <p id={descId} style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)', margin: 0 }}>
        {summary}
      </p>
      <button
        type="button"
        onClick={() => setShowTable((s) => !s)}
        aria-expanded={showTable}
        style={{
          marginTop: space['2'],
          background: 'transparent',
          border: 'none',
          padding: 0,
          cursor: 'pointer',
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          color: c.accent,
        }}
      >
        {showTable ? 'Hide table' : 'Show as table'}
      </button>
      {showTable && (
        <ChartTable
          caption={title}
          columns={[
            'Period',
            ...(series.length > 1 ? series.map((s) => s.label) : [unit[0].toUpperCase() + unit.slice(1)]),
          ]}
          rows={rows.map((r) => [r.label, ...series.map((s) => r.values[s.key] ?? 0)])}
        />
      )}
    </div>
  );
}
