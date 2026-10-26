/**
 * The report's processing note, shown above the body (T-8.8.4.4).
 *
 * The compose step discloses in the report itself what the pipeline dropped,
 * trimmed or repaired (S-1.12.4, S-1.14.17) as one paragraph at the end of
 * the HTML. In the reader that paragraph lost its styling to the sanitiser
 * and sat after the statistics, where nobody reads; a section closed after
 * being cut off mid-markup was disclosed there and nowhere else. The parser
 * lifts the paragraph out (`ParsedReport.processingNotes`) and this callout
 * puts it before the text it qualifies.
 */
import type { ReactNode } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../../theme';

export function ProcessingNote({ notes }: { notes: ReactNode[] }) {
  const c = useColors();
  if (notes.length === 0) return null;
  return (
    <aside
      role="note"
      aria-label="Processing note"
      style={{
        maxWidth: measure.reading,
        margin: `0 0 ${space['6']}`,
        padding: `${space['2']} ${space['3']}`,
        background: c.warnSubtle,
        border: `1px solid ${c.warn}`,
        borderLeft: `3px solid ${c.warn}`,
        borderRadius: radius.md,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        color: c.textPrimary,
        lineHeight: lineHeight.snug,
        overflowWrap: 'anywhere',
      }}
    >
      {notes.map((note, i) => (
        <p key={i} style={{ margin: i === 0 ? 0 : `${space['2']} 0 0` }}>
          {i === 0 && (
            <strong style={{ color: c.warn, fontWeight: fontWeight.semibold }}>Processing note: </strong>
          )}
          {note}
        </p>
      ))}
    </aside>
  );
}
