import type { CSSProperties } from 'react';
import { useColors } from '../../hooks/useTheme';
import { useUsageSummary } from '../../hooks/useUsageSummary';
import { usageLines, type UsageAmounts } from '../../services/usageApi';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';

/**
 * E-5.2: what the signed-in user has spent, by feature: model tokens and
 * calls, YouTube Data API units and audio sent to Whisper, today and over the
 * last 30 days.
 * Read-only and informational: nothing shown here is a limit (D-111 took the
 * daily-token line off the pricing page because nothing enforced it).
 */
export function UsageSummaryPanel() {
  const c = useColors();
  const { data, isLoading, isError } = useUsageSummary();

  const muted: CSSProperties = {
    margin: 0,
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    color: c.textSecondary,
    lineHeight: lineHeight.normal,
  };
  const th: CSSProperties = {
    textAlign: 'left',
    padding: `${space['2']} ${space['3']}`,
    fontFamily: fonts.ui,
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
    color: c.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
    borderBottom: `1px solid ${c.border}`,
  };
  const td: CSSProperties = {
    padding: `${space['2']} ${space['3']}`,
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    color: c.textPrimary,
    lineHeight: lineHeight.snug,
    verticalAlign: 'top',
    borderBottom: `1px solid ${c.border}`,
    overflowWrap: 'anywhere',
  };

  const cell = (a: UsageAmounts) => {
    const lines = usageLines(a);
    if (lines.length === 0) return <span style={{ color: c.textMuted }}>—</span>;
    return lines.map((l, i) => (
      <div key={l} style={i === 0 ? undefined : { color: c.textSecondary, fontSize: fontSize.xs }}>
        {l}
      </div>
    ));
  };

  return (
    <section
      aria-labelledby="usage-summary-heading"
      data-usage-summary
      style={{
        marginTop: space['7'],
        background: c.surface,
        border: `1px solid ${c.border}`,
        borderRadius: radius.lg,
        padding: `${space['5']} ${space['4']}`,
      }}
    >
      <h2
        id="usage-summary-heading"
        style={{
          margin: 0,
          fontFamily: fonts.display,
          fontSize: fontSize.xl,
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
        }}
      >
        Your usage
      </h2>
      <p style={{ ...muted, margin: `${space['2']} 0 ${space['4']}` }}>
        Model tokens, YouTube Data API units and audio transcribed by Whisper for your work, today and over
        the last 30 days (UTC days). Recorded for your information; none of it is limited. Local models report
        no token counts, so only their calls are counted.
      </p>

      {isLoading ? (
        <p style={muted}>Loading usage…</p>
      ) : isError || !data ? (
        <p role="alert" style={muted}>
          Could not load your usage. Try again later.
        </p>
      ) : data.features.length === 0 ? (
        <p data-usage-empty style={muted}>
          Nothing recorded in the last 30 days. Usage appears here after you ask a question, run a job, or
          generate a report.
        </p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
          <thead>
            <tr>
              <th scope="col" style={{ ...th, width: '38%' }}>
                Feature
              </th>
              <th scope="col" style={th}>
                Today
              </th>
              <th scope="col" style={th}>
                Last 30 days
              </th>
            </tr>
          </thead>
          <tbody>
            {data.features.map((row) => (
              <tr key={row.feature} data-usage-feature={row.feature}>
                <th scope="row" style={{ ...td, fontWeight: fontWeight.medium }}>
                  {row.label}
                </th>
                <td style={td}>{cell(row.today)}</td>
                <td style={td}>{cell(row.last_30_days)}</td>
              </tr>
            ))}
            <tr data-usage-total>
              <th scope="row" style={{ ...td, fontWeight: fontWeight.semibold, borderBottom: 'none' }}>
                Total
              </th>
              <td style={{ ...td, borderBottom: 'none' }}>{cell(data.totals.today)}</td>
              <td style={{ ...td, borderBottom: 'none' }}>{cell(data.totals.last_30_days)}</td>
            </tr>
          </tbody>
        </table>
      )}
      {data && data.metered_since && data.metered_since > data.window_start && (
        <p data-usage-since style={{ ...muted, marginTop: space['3'], fontSize: fontSize.xs }}>
          Recording started on {data.metered_since}, so the 30-day figures cover less than 30 days.
        </p>
      )}
    </section>
  );
}
