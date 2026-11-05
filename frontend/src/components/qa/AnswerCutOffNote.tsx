/**
 * T-1.15.4.5: an answer that stopped at its token budget says so under its text,
 * as a cut-off knowledge report does (`KnowledgeCutOffNote`). It offers Deep
 * rather than the next step up, for the same reason (D-132). An answer already at
 * Deep has nothing deeper to offer, so it gets the note alone.
 *
 * The offer fills the composer and picks Deep; it does not ask. A question goes
 * through its page's own scope and clarify step, and what the reader told the
 * clarify step the first time is not stored, so re-sending it blind could answer
 * a different question. Nothing is spent until they press Ask.
 *
 * Shows nothing for an answer this session did not see being cut, which is every
 * answer after a reload (`qaCutOffStore`).
 */
import { Button } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, lineHeight, radius, space } from '../../theme';
import { useQACutOffStore } from '../../stores/qaCutOffStore';
import { depthLabel, type Depth } from '../../utils/depth';

const DEEPEST: Depth = 'deep';

interface Props {
  exchangeId: string;
  /** The depth an ask that carried none ran at: a run's own, on the job page. */
  inheritedDepth?: Depth | null;
  /** Left out while asking is unavailable or an answer is on its way. */
  onAskAgain?: () => void;
}

export function AnswerCutOffNote({ exchangeId, inheritedDepth = null, onAskAgain }: Props) {
  const c = useColors();
  const askedAt = useQACutOffStore((s) => s.answers[exchangeId]);
  if (askedAt === undefined) return null;
  const offer = (askedAt ?? inheritedDepth) !== DEEPEST ? onAskAgain : undefined;
  const label = depthLabel(DEEPEST);
  return (
    <div
      role="note"
      data-answer-cut-off=""
      style={{
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: space['3'],
        padding: space['3'],
        marginTop: space['3'],
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
        This answer stopped at its length limit, so its end is missing.
        {offer && ` Asking again at ${label} depth gives it more room and uses one question.`}
      </p>
      {offer && (
        <Button
          size="sm"
          variant="secondary"
          onClick={offer}
          title={`Puts this question back in the box with ${label} picked. Nothing is spent until you ask.`}
        >
          Ask again at {label} depth
        </Button>
      )}
    </div>
  );
}
