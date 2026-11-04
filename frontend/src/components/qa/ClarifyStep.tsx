/**
 * The clarify step between typing a question and asking it, for the library
 * page and the shelf panel: how the question was understood, the optional
 * clarifying questions, and "Confirm & search" or "Skip clarifications".
 * The surface owns the state and the ask; `buildClarifyContext` turns what the
 * reader typed here into the request's `context`.
 */
import { Button, FormField, Input } from '../primitives';
import { InfoStripe } from './LibraryQAExchangeCard';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { CLARIFY_ANSWER_MAX_CHARS } from '../../utils/clarifyContext';

interface Props {
  question: string;
  interpretation: string;
  clarifications: string[];
  answers: string[];
  onAnswersChange: (answers: string[]) => void;
  onEdit: () => void;
  onConfirm: () => void;
  onSkip: () => void;
  /** The ask is running. */
  pending: boolean;
  /** Shown while the ask runs. */
  pendingText: string;
  disabled: boolean;
  disabledTitle?: string;
}

export function ClarifyStep({
  question,
  interpretation,
  clarifications,
  answers,
  onAnswersChange,
  onEdit,
  onConfirm,
  onSkip,
  pending,
  pendingText,
  disabled,
  disabledTitle,
}: Props) {
  const c = useColors();
  return (
    <div
      style={{
        marginBottom: space['5'],
        padding: space['4'],
        background: c.surfaceAlt,
        borderRadius: radius.md,
        border: `1px solid ${c.border}`,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: space['3'],
          marginBottom: space['3'],
        }}
      >
        <p
          style={{
            margin: 0,
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            color: c.textMuted,
            letterSpacing: '0.04em',
            textTransform: 'uppercase',
          }}
        >
          Your question:{' '}
          <em
            style={{
              color: c.textSecondary,
              fontStyle: 'italic',
              textTransform: 'none',
              letterSpacing: '0',
              fontSize: fontSize.sm,
            }}
          >
            {question}
          </em>
        </p>
        <Button size="sm" variant="tertiary" onClick={onEdit}>
          ← Edit
        </Button>
      </div>

      <div
        style={{
          marginBottom: space['4'],
          padding: space['3'],
          background: c.accentSubtle,
          borderRadius: radius.md,
          borderLeft: `3px solid ${c.accent}`,
        }}
      >
        <p
          style={{
            margin: 0,
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            fontWeight: fontWeight.semibold,
            color: c.accent,
            marginBottom: space['1'],
            letterSpacing: '0.04em',
            textTransform: 'uppercase',
          }}
        >
          Here's how I understand your question
        </p>
        <p
          style={{
            margin: 0,
            fontFamily: fonts.body,
            fontSize: fontSize.base,
            color: c.textPrimary,
            lineHeight: lineHeight.normal,
          }}
        >
          {interpretation}
        </p>
      </div>

      {clarifications.length > 0 && (
        <div style={{ marginBottom: space['4'] }}>
          <p
            style={{
              margin: `0 0 ${space['3']}`,
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              fontWeight: fontWeight.semibold,
              color: c.textSecondary,
            }}
          >
            A few clarifying questions (optional — answer any that are useful):
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
            {clarifications.map((q, i) => (
              <FormField key={i} label={q}>
                {(controlId) => (
                  <Input
                    id={controlId}
                    value={answers[i] ?? ''}
                    onChange={(e) => {
                      const next = [...answers];
                      next[i] = e.target.value;
                      onAnswersChange(next);
                    }}
                    placeholder="Your answer (optional)"
                    maxLength={CLARIFY_ANSWER_MAX_CHARS}
                    disabled={pending}
                  />
                )}
              </FormField>
            ))}
          </div>
        </div>
      )}

      {pending && <InfoStripe text={pendingText} />}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['2'], marginTop: space['3'] }}>
        <Button
          variant="primary"
          onClick={onConfirm}
          disabled={disabled}
          loading={pending}
          title={disabledTitle}
        >
          Confirm & search
        </Button>
        <Button variant="tertiary" onClick={onSkip} disabled={disabled} title={disabledTitle}>
          Skip clarifications
        </Button>
      </div>
    </div>
  );
}
