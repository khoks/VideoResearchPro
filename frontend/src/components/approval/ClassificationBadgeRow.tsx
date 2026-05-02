/**
 * <ClassificationBadgeRow>
 *
 * Renders the four-axis classification (stance / sentiment / framing /
 * topic_relevance) for one approval candidate as a row of three Badges
 * with a topic-relevance percentage chip alongside.
 *
 * Per D-014 / D-021 / D-023: classification is a hint surface, never
 * a hard gate. Low-relevance candidates (`topic_relevance < 0.5`) are
 * still rendered but the row is dimmed so the eye glides past them.
 *
 * Tone mapping (intentionally opinionated):
 * - stance:    for=success, against=error, neutral/unclear=neutral
 * - sentiment: positive=success, negative=error, mixed=warn, neutral=neutral
 * - framing:   technical=info, political=accent, emotional=warn,
 *              experiential=success
 *
 * Visual collisions are tolerated — the prefix label ("Stance:" /
 * "Sent:" / "Frame:") disambiguates. The intent is mood-signal at
 * a glance, not strict identity.
 *
 * The full breakdown (including the literal axis values + topic_relevance
 * percentage) renders as a `title` tooltip on hover. T-1.5.4.2 leaves
 * richer custom-tooltip rendering for a follow-up if the native title
 * proves insufficient.
 */
import type { CSSProperties } from 'react';
import { Badge, type BadgeTone } from '../primitives/Badge';
import { fonts, fontSize, fontWeight, space } from '../../theme';
import type { Classification } from './types';

/**
 * Hide-cutoff per D-021. Below this threshold the candidate is normally
 * filtered out of the default approval list, but if the user toggles
 * "Show low-relevance candidates" we render it dimmed so the eye glides
 * past while keeping the badge available for inspection.
 */
const TOPIC_RELEVANCE_THRESHOLD: number = 0.5;

const STANCE_TONE: Record<Classification['stance'], BadgeTone> = {
  for: 'success',
  against: 'error',
  neutral: 'neutral',
  unclear: 'neutral',
};

const SENTIMENT_TONE: Record<Classification['sentiment'], BadgeTone> = {
  positive: 'success',
  negative: 'error',
  mixed: 'warn',
  neutral: 'neutral',
};

const FRAMING_TONE: Record<Classification['framing'], BadgeTone> = {
  technical: 'info',
  political: 'accent',
  emotional: 'warn',
  experiential: 'success',
};

/** Title-case the axis value for display. */
function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export interface ClassificationBadgeRowProps {
  classification?: Classification;
  /**
   * When true, the row stays visible even if `topic_relevance` is below
   * the threshold (just dimmed). Drives the "Show low-relevance
   * candidates" toggle behavior. Default: false (consumer's filter chip
   * controls whether the candidate is rendered at all).
   */
  showLowRelevance?: boolean;
  style?: CSSProperties;
}

export function ClassificationBadgeRow({
  classification,
  showLowRelevance = true,
  style,
}: ClassificationBadgeRowProps) {
  if (!classification) {
    return null;
  }

  const isLowRelevance = classification.topic_relevance < TOPIC_RELEVANCE_THRESHOLD;
  if (isLowRelevance && !showLowRelevance) {
    return null;
  }

  const relevancePercent = Math.round(classification.topic_relevance * 100);

  const tooltip =
    `Stance: ${titleCase(classification.stance)}\n` +
    `Sentiment: ${titleCase(classification.sentiment)}\n` +
    `Framing: ${titleCase(classification.framing)}\n` +
    `Topic relevance: ${relevancePercent}%`;

  const rowStyle: CSSProperties = {
    display: 'inline-flex',
    flexWrap: 'wrap',
    gap: space['2'],
    alignItems: 'center',
    fontFamily: fonts.ui,
    fontSize: fontSize.xs,
    fontWeight: fontWeight.medium,
    opacity: isLowRelevance ? 0.55 : 1,
    transition: 'opacity 120ms cubic-bezier(0.2, 0.8, 0.2, 1)',
    ...style,
  };

  return (
    <span
      style={rowStyle}
      role="group"
      aria-label="Stance, sentiment, framing, and topic-relevance classification"
      title={tooltip}
    >
      <Badge tone={STANCE_TONE[classification.stance]} size="sm">
        Stance: {titleCase(classification.stance)}
      </Badge>
      <Badge tone={SENTIMENT_TONE[classification.sentiment]} size="sm">
        Sent: {titleCase(classification.sentiment)}
      </Badge>
      <Badge tone={FRAMING_TONE[classification.framing]} size="sm">
        Frame: {titleCase(classification.framing)}
      </Badge>
      <Badge tone={isLowRelevance ? 'neutral' : 'info'} size="sm">
        {relevancePercent}% relevant
      </Badge>
    </span>
  );
}
