import { useColors } from '../../hooks/useTheme';
import { fontSize, fontWeight, fonts, lineHeight, radius, space } from '../../theme';
import type { Job } from '../../types/job';

/**
 * S-1.5.14: what a run has to say about its sources and limits: one that was
 * unavailable or found nothing, a share given to the others, a Whisper limit
 * reached. The server writes the sentences. Renders nothing on a run with
 * nothing to say. A failed run's error already names what was unavailable.
 */
export function RunNotes({ job }: { job: Pick<Job, 'status' | 'run_notes'> }) {
  const c = useColors();
  const notes = (job.run_notes ?? []).filter(
    (note) => job.status !== 'failed' || note.kind !== 'source_unavailable',
  );
  if (notes.length === 0) return null;
  return (
    <div
      role="note"
      data-testid="run-notes"
      style={{
        marginTop: space['3'],
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
      <strong style={{ color: c.warn, fontWeight: fontWeight.semibold }}>About this run's sources</strong>
      <ul style={{ margin: `${space['1']} 0 0`, paddingLeft: space['4'] }}>
        {notes.map((note) => (
          <li key={`${note.kind}:${note.source_type ?? ''}`}>{note.text}</li>
        ))}
      </ul>
    </div>
  );
}
