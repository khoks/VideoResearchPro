/**
 * Inline citation chip inside report prose (S-8.8.1).
 *
 * A resolved citation links to the source at its timestamp. An unresolved one
 * (pre-S-1.14.9 reports whose anchors carried only `&t=`) keeps the timestamp
 * visible but is not a link — a dead link is worse than plain text.
 *
 * S-8.8.2 upgrades this to numbered chips with hover / focus cards.
 */
import type { CSSProperties } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, radius, space } from '../../theme';
import type { ReportCitation } from './parseReport';

export function ReaderCitation({ citation }: { citation: ReportCitation }) {
  const c = useColors();
  const base: CSSProperties = {
    display: 'inline-block',
    fontFamily: fonts.mono,
    fontSize: fontSize.xs,
    lineHeight: 1.6,
    padding: `0 ${space['2']}`,
    borderRadius: radius.pill,
    border: `1px solid ${c.border}`,
    whiteSpace: 'nowrap',
    verticalAlign: 'baseline',
    textDecoration: 'none',
  };

  if (citation.href) {
    return (
      <a
        className="reader-citation"
        href={citation.href}
        target="_blank"
        rel="noopener noreferrer"
        title={`Open the source at ${citation.label}`}
        style={{ ...base, color: c.accent, background: c.accentSubtle }}
      >
        {citation.label}
      </a>
    );
  }

  return (
    <span
      className="reader-citation reader-citation--unresolved"
      title="Timestamp in the source; this report did not record the link"
      style={{ ...base, color: c.textMuted, background: c.surfaceAlt }}
    >
      {citation.label}
    </span>
  );
}
