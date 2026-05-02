import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  useAskLibraryQA,
  useClarifyLibraryQA,
  useLibraryQAHistory,
} from '../hooks/useLibraryQA';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import { CitationLink } from '../components/citation';
import {
  Badge,
  Button,
  Card,
  FormField,
  Input,
  Select,
  Spinner,
} from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import {
  fonts,
  fontSize,
  fontWeight,
  lineHeight,
  measure,
  radius,
  space,
} from '../theme';
import type { AnswerLanguage, LibraryQAExchange } from '../types/qa';

const FEATURE_UNAVAILABLE_MSG = 'LLM-dependent feature is temporarily unavailable';

const LANGUAGE_OPTIONS: Array<{ value: AnswerLanguage; label: string }> = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'हिन्दी' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
];

export function LibraryQAPage() {
  const c = useColors();
  const { data: history } = useLibraryQAHistory();
  const askQuestion = useAskLibraryQA();
  const clarifyQuestion = useClarifyLibraryQA();
  const libraryQAAvailable = useFeatureAvailable('library_qa');

  const [question, setQuestion] = useState('');
  const [language, setLanguage] = useState<AnswerLanguage>('en');
  const [step, setStep] = useState<'ask' | 'clarify'>('ask');
  const [interpretation, setInterpretation] = useState('');
  const [clarifications, setClarifications] = useState<string[]>([]);
  const [clarificationAnswers, setClarificationAnswers] = useState<string[]>([]);

  const askInputDisabled = clarifyQuestion.isPending || !libraryQAAvailable;
  const askButtonDisabled = askInputDisabled || !question.trim();
  const clarifyButtonsDisabled = askQuestion.isPending || !libraryQAAvailable;

  const resetToAsk = () => {
    setStep('ask');
    setInterpretation('');
    setClarifications([]);
    setClarificationAnswers([]);
  };

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || !libraryQAAvailable) return;
    const result = await clarifyQuestion.mutateAsync({ question });
    setInterpretation(result.interpretation);
    setClarifications(result.clarifications);
    setClarificationAnswers(new Array(result.clarifications.length).fill(''));
    setStep('clarify');
  };

  const handleConfirmSearch = async () => {
    if (!libraryQAAvailable) return;
    const answeredParts = clarifications
      .map((q, i) => (clarificationAnswers[i]?.trim() ? `${q}\n${clarificationAnswers[i].trim()}` : null))
      .filter(Boolean) as string[];

    const context = [
      `My interpretation: ${interpretation}`,
      ...answeredParts,
    ].join('\n\n');

    await askQuestion.mutateAsync({ question, answer_language: language, context });
    setQuestion('');
    resetToAsk();
  };

  const handleSkipAndAsk = async () => {
    if (!libraryQAAvailable) return;
    await askQuestion.mutateAsync({ question, answer_language: language });
    setQuestion('');
    resetToAsk();
  };

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
      <header style={{ marginBottom: space['5'] }}>
        <h1
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            margin: 0,
            lineHeight: lineHeight.tight,
          }}
        >
          Ask the whole library
        </h1>
        <p
          style={{
            fontFamily: fonts.body,
            fontStyle: 'italic',
            fontSize: fontSize.sm,
            color: c.textMuted,
            margin: `${space['2']} 0 0`,
            maxWidth: measure.reading,
          }}
        >
          Questions travel every shelf — every transcript you've ever gathered. Answers come back grounded in the corpus with timestamped citations.
        </p>
      </header>

      <Card>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: space['4'],
            flexWrap: 'wrap',
            marginBottom: space['4'],
          }}
        >
          <h2
            style={{
              margin: 0,
              fontFamily: fonts.display,
              fontSize: fontSize.lg,
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
            }}
          >
            New question
          </h2>
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: space['2'],
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              color: c.textSecondary,
            }}
          >
            Answer language
            <Select
              value={language}
              onChange={(e) => setLanguage(e.target.value as AnswerLanguage)}
              style={{ width: 'auto', minWidth: 140 }}
            >
              {LANGUAGE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
          </label>
        </div>

        {step === 'ask' && (
          <>
            {!libraryQAAvailable && (
              <div
                role="alert"
                style={{
                  marginBottom: space['3'],
                  padding: space['3'],
                  borderRadius: radius.md,
                  background: c.warnSubtle,
                  border: `1px solid ${c.warn}`,
                  color: c.warn,
                  fontFamily: fonts.ui,
                  fontSize: fontSize.sm,
                }}
              >
                {FEATURE_UNAVAILABLE_MSG}.
              </div>
            )}
            <form
              onSubmit={handleAsk}
              style={{
                display: 'flex',
                gap: space['2'],
                marginBottom: space['4'],
                flexWrap: 'wrap',
              }}
            >
              <div style={{ flex: '1 1 280px' }}>
                <Input
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder={
                    libraryQAAvailable
                      ? 'Ask a question about your entire library…'
                      : FEATURE_UNAVAILABLE_MSG
                  }
                  disabled={askInputDisabled}
                  title={!libraryQAAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
                  aria-label="Question"
                />
              </div>
              <Button
                type="submit"
                disabled={askButtonDisabled}
                loading={clarifyQuestion.isPending}
                title={!libraryQAAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
              >
                Ask
              </Button>
            </form>
            {clarifyQuestion.isPending && <InfoStripe text="Listening for the echo of your question…" />}
          </>
        )}

        {step === 'clarify' && (
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
              <Button size="sm" variant="tertiary" onClick={resetToAsk}>
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
                          value={clarificationAnswers[i] ?? ''}
                          onChange={(e) => {
                            const next = [...clarificationAnswers];
                            next[i] = e.target.value;
                            setClarificationAnswers(next);
                          }}
                          placeholder="Your answer (optional)"
                          disabled={askQuestion.isPending}
                        />
                      )}
                    </FormField>
                  ))}
                </div>
              </div>
            )}

            {askQuestion.isPending && <InfoStripe text="Searching the library and generating answer…" />}

            <div style={{ display: 'flex', gap: space['2'], marginTop: space['3'] }}>
              <Button
                variant="primary"
                onClick={handleConfirmSearch}
                disabled={clarifyButtonsDisabled}
                loading={askQuestion.isPending}
                title={!libraryQAAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
              >
                Confirm & search
              </Button>
              <Button
                variant="tertiary"
                onClick={handleSkipAndAsk}
                disabled={clarifyButtonsDisabled}
                title={!libraryQAAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
              >
                Skip clarifications
              </Button>
            </div>
          </div>
        )}

        {history && history.length > 0 && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: space['3'],
              marginTop: step === 'clarify' ? 0 : space['4'],
            }}
          >
            {history.map((qa) => (
              <LibraryQAExchangeCard key={qa.id} qa={qa} />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function InfoStripe({ text }: { text: string }) {
  const c = useColors();
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: space['3'],
        marginBottom: space['3'],
        padding: space['3'],
        background: c.accentSubtle,
        borderRadius: radius.md,
      }}
    >
      <Spinner size={16} />
      <span
        style={{
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          color: c.accent,
          fontWeight: fontWeight.medium,
        }}
      >
        {text}
      </span>
    </div>
  );
}

function LibraryQAExchangeCard({ qa }: { qa: LibraryQAExchange }) {
  const c = useColors();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(qa.answer);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable (e.g. insecure context) — leave button state unchanged
    }
  };

  return (
    <div
      style={{
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
            flex: 1,
            fontFamily: fonts.display,
            fontSize: fontSize.md,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            lineHeight: lineHeight.snug,
          }}
        >
          {qa.question}
        </p>
        <Button size="sm" variant="tertiary" onClick={handleCopy}>
          {copied ? (
            <Badge tone="success" size="sm">
              Copied
            </Badge>
          ) : (
            'Copy answer'
          )}
        </Button>
      </div>
      <div
        className="reading"
        style={{
          color: c.textPrimary,
          fontFamily: fonts.body,
          fontSize: fontSize.base,
          lineHeight: lineHeight.loose,
        }}
      >
        <ReactMarkdown>{qa.answer}</ReactMarkdown>
      </div>
      {qa.references.length > 0 && (
        <div
          style={{
            marginTop: space['3'],
            borderTop: `1px solid ${c.border}`,
            paddingTop: space['3'],
          }}
        >
          <span
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.xs,
              fontWeight: fontWeight.semibold,
              color: c.textSecondary,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}
          >
            References
          </span>
          <div style={{ marginTop: space['2'], display: 'flex', flexDirection: 'column', gap: space['1'] }}>
            {qa.references.map((ref, i) => (
              <CitationLink key={i} reference={ref} style={{ fontSize: fontSize.sm }} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
