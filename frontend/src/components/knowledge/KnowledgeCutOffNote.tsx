/**
 * T-1.15.3.8: a knowledge report that stopped at its token budget says so
 * where it is read, and offers the depth with the most room. Deep rather than
 * the next step up, because a Regenerate is metered and on a short source
 * Standard's ceiling is barely above Brief's (D-125). A report already at Deep
 * has nothing deeper to offer, so it gets the note alone. The caller leaves
 * `onRegenerate` out while extraction is unavailable.
 *
 * The note prints with the report (it is about the report); the button does not.
 */
import { Button } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, lineHeight, radius, space } from '../../theme';
import { depthLabel, type Depth } from '../../utils/depth';

const DEEPEST: Depth = 'deep';

interface Props {
  /** The depth the report was written at; null when none was asked for. */
  writtenAt: Depth | null;
  onRegenerate?: (depth: Depth) => void;
  busy?: boolean;
}

export function KnowledgeCutOffNote({ writtenAt, onRegenerate, busy = false }: Props) {
  const c = useColors();
  const regenerate = writtenAt !== DEEPEST ? onRegenerate : undefined;
  const label = depthLabel(DEEPEST);
  return (
    <div
      role="note"
      data-knowledge-cut-off=""
      style={{
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: space['3'],
        padding: space['3'],
        marginBottom: space['4'],
        background: c.warnSubtle,
        borderRadius: radius.md,
        border: `1px solid ${c.warn}`,
      }}
    >
      <p
        style={{
          flex: '1 1 260px',
          margin: 0,
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          color: c.textPrimary,
          lineHeight: lineHeight.snug,
        }}
      >
        This report stopped at its length limit, so its end is missing.
        {regenerate && ` Regenerating at ${label} depth gives it more room and uses one knowledge extraction.`}
      </p>
      {regenerate && (
        <span className="reader-no-print">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => regenerate(DEEPEST)}
            loading={busy}
            title="Re-run extraction; overwrites the stored report."
          >
            Regenerate at {label} depth
          </Button>
        </span>
      )}
    </div>
  );
}
