import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { SuggestionCard } from '../components/qa/SuggestionCard';
import { useLibraryVideos } from '../hooks/useLibrary';
import {
  useAskLibraryQA,
  useClarifyLibraryQA,
  useLibraryQAHistory,
} from '../hooks/useLibraryQA';
import { useDepthChoice } from '../hooks/useDepthChoice';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import { usePreferredDepth } from '../hooks/useMe';
import { ClarifyStep } from '../components/qa/ClarifyStep';
import { DockedComposer, QADock, QAThread } from '../components/qa/Composer';
import { InfoStripe, LibraryQAExchangeCard } from '../components/qa/LibraryQAExchangeCard';
import { useExchangeFocus } from '../hooks/useExchangeFocus';
import { ComposerDepthNote, DepthSelect } from '../components/common/DepthSelect';
import {
  Button,
  Card,
  EmptyState,
  Input,
  Select,
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
import type { AnswerLanguage, QAScope, SourceScope } from '../types/qa';
import { buildClarifyContext } from '../utils/clarifyContext';
import { withDepth } from '../utils/depth';

const FEATURE_UNAVAILABLE_MSG = 'LLM-dependent feature is temporarily unavailable';

/** What the knowledge drawer hands over as route state (T-8.4.2.4). */
interface HandOver {
  question?: string;
  ask?: boolean;
  source?: SourceScope;
}

const LANGUAGE_OPTIONS: Array<{ value: AnswerLanguage; label: string }> = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'हिन्दी' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
];

export function LibraryQAPage() {
  const c = useColors();
  const { data: history } = useLibraryQAHistory();
  const navigate = useNavigate();
  // S-8.10.2: with nothing in the library there is nothing to ask; say so
  // and offer the one action that fixes it, instead of a composer that can
  // only answer "no sources".
  const firstSource = useLibraryVideos({ limit: 1 });
  const libraryEmpty = firstSource.isSuccess && firstSource.data.length === 0 && !(history && history.length > 0);
  const askQuestion = useAskLibraryQA();
  const clarifyQuestion = useClarifyLibraryQA();
  const libraryQAAvailable = useFeatureAvailable('library_qa');

  const [question, setQuestion] = useState('');
  const [language, setLanguage] = useState<AnswerLanguage>('en');
  // R4: the next ask's depth, and that ask's only: once the answer lands it goes
  // back to where this page starts, which is the account's default depth, if
  // any (T-1.15.3.9). Null sends none and the corpus size decides.
  const { depth, pick: setDepth, reset: resetDepth } = useDepthChoice(usePreferredDepth());
  const [step, setStep] = useState<'ask' | 'clarify'>('ask');
  const [interpretation, setInterpretation] = useState('');
  const [clarifications, setClarifications] = useState<string[]>([]);
  const [clarificationAnswers, setClarificationAnswers] = useState<string[]>([]);
  // T-8.4.2.4: while set, every question here is asked about this source
  // alone; "Ask the whole library" clears it.
  const [source, setSource] = useState<SourceScope | null>(null);
  const scoped = (body: { question: string; answer_language: AnswerLanguage; context?: string }) =>
    source ? { ...body, document_id: source.id } : body;

  // S-8.13.3: a failed clarify asks from the render that started it, so what that
  // ask carries is held, not only the question: the page must show what it sends.
  const asking = clarifyQuestion.isPending || askQuestion.isPending;
  const askInputDisabled = asking || !libraryQAAvailable;
  const askButtonDisabled = askInputDisabled || !question.trim();
  const clarifyButtonsDisabled = askQuestion.isPending || !libraryQAAvailable;

  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const questionInput = useRef<HTMLInputElement>(null);

  const resetToAsk = () => {
    setStep('ask');
    setInterpretation('');
    setClarifications([]);
    setClarificationAnswers([]);
  };

  // An answer landed. "Edit" uses resetToAsk alone: that is still the same
  // ask, so it keeps the depth; a failed ask keeps it for the retry.
  const finishAsk = () => {
    setQuestion('');
    resetDepth();
    resetToAsk();
  };

  // T-1.15.4.5: a cut-off answer's offer; see `AnswerCutOffNote`. Not while a
  // clarify runs: its reply would land on the question the offer put here.
  const askAtDeep = (q: string) => {
    resetToAsk();
    setQuestion(q);
    setDepth('deep');
    setTimeout(() => questionInput.current?.focus(), 0);
  };
  const askAgain = libraryQAAvailable && !asking ? askAtDeep : undefined;
  // The offer only fills this composer, so the next ask runs over this page's
  // scope. The history also holds shelf and one-source exchanges, and offering on
  // those would widen or narrow the question without a word. They get the note
  // alone, and their scope note links back to where they were asked.
  const asksHere = (scope: QAScope | null | undefined) =>
    !scope?.shelf_id && (scope?.document_id ?? null) === (source?.id ?? null);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || !libraryQAAvailable) return;
    let result;
    try {
      result = await clarifyQuestion.mutateAsync({ question });
    } catch {
      // S-8.13.3: clarifying is optional (D-132). The global mutation cache
      // already toasted the failure, and an outage in this step must not stop
      // an ask that does not need it. A page the reader has left asks nothing:
      // that call settled after they moved on.
      if (mounted.current) await handleSkipAndAsk();
      return;
    }
    setInterpretation(result.interpretation);
    setClarifications(result.clarifications);
    setClarificationAnswers(new Array(result.clarifications.length).fill(''));
    setStep('clarify');
  };

  const handleConfirmSearch = async () => {
    if (!libraryQAAvailable) return;
    // Kept under the server's 4,000-character bound, or the ask is a 422.
    const context = buildClarifyContext(interpretation, clarifications, clarificationAnswers);

    await askQuestion.mutateAsync(withDepth(scoped({ question, answer_language: language, context }), depth));
    finishAsk();
  };

  const handleSkipAndAsk = async () => {
    if (!libraryQAAvailable) return;
    try {
      await askQuestion.mutateAsync(withDepth(scoped({ question, answer_language: language }), depth));
    } catch {
      return; // the global mutation cache already toasted; the question stays
    }
    finishAsk();
  };

  // S-8.4.2: Shift-click on a suggestion asks at once (no clarify step).
  const askSuggestion = async (q: string, about: SourceScope | null = source) => {
    if (!libraryQAAvailable) return;
    setQuestion(q);
    try {
      const body = { question: q, answer_language: language };
      await askQuestion.mutateAsync(withDepth(about ? { ...body, document_id: about.id } : body, depth));
    } catch {
      return; // the global mutation cache already toasted
    }
    finishAsk();
  };

  // A suggestion picked in the knowledge drawer arrives as route state:
  // fill the composer, or ask at once for a Shift-click, about that source
  // (T-8.4.2.4). Once per visit.
  const location = useLocation();
  const handedOver = useRef(false);
  useEffect(() => {
    const state = location.state as HandOver | null;
    if (handedOver.current || !state?.question) return;
    handedOver.current = true;
    navigate(location.pathname, { replace: true, state: null });
    const about = state.source?.id ? state.source : null;
    setSource(about);
    if (state.ask) void askSuggestion(state.question, about);
    else setQuestion(state.question);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state]);

  // `?exchange=<id>` from the palette lands on that card (S-8.2.2).
  useExchangeFocus(!!history?.length);

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
          {source ? 'Ask one source' : 'Ask the whole library'}
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
          {source
            ? 'Questions here stay inside one source, and answers cite only it.'
            : "Questions travel every shelf — every transcript you've ever gathered. Answers come back grounded in the corpus with timestamped citations."}
        </p>
      </header>

      {libraryEmpty ? (
        <EmptyState
          title="Nothing to ask yet."
          description="Library questions are answered from the sources you have ingested, and there are none yet. Start a run, or upload a PDF or paste a link."
          action={<Button onClick={() => navigate('/library?tab=ingest')}>Add sources</Button>}
        />
      ) : (
      <Card>
        <QADock>
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
          <div style={{ display: 'flex', alignItems: 'center', gap: space['4'], flexWrap: 'wrap' }}>
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
                disabled={asking}
              >
                {LANGUAGE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            </label>
            {/* R4: a per-ask override beside the other per-ask option. */}
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
              Answer depth
              <DepthSelect
                value={depth}
                onChange={setDepth}
                unsetLabel="Default"
                aria-label="Answer depth"
                title="Default: sized to how much of your library the question draws on."
                disabled={asking}
              />
            </label>
          </div>
        </div>

        {source && (
          <SourceScopeChip source={source} onClear={() => setSource(null)} disabled={asking} />
        )}

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
            <DockedComposer>
            <ComposerDepthNote depth={depth} onClear={() => setDepth(null)} disabled={asking} />
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
                  ref={questionInput}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder={
                    !libraryQAAvailable
                      ? FEATURE_UNAVAILABLE_MSG
                      : source
                        ? 'Ask a question about this source…'
                        : 'Ask a question about your entire library…'
                  }
                  disabled={askInputDisabled}
                  title={!libraryQAAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
                  aria-label="Question"
                />
              </div>
              <Button
                type="submit"
                disabled={askButtonDisabled}
                loading={clarifyQuestion.isPending || askQuestion.isPending}
                title={!libraryQAAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
              >
                Ask
              </Button>
            </form>
            </DockedComposer>
            {clarifyQuestion.isPending && <InfoStripe text="Listening for the echo of your question…" />}
            {askQuestion.isPending && <InfoStripe text="Searching the library and generating answer…" />}
            {!askQuestion.isPending && (
              <SuggestionCard
                context={source ? `document:${source.id}` : 'library'}
                enabled={libraryQAAvailable}
                onFill={setQuestion}
                onAsk={(q) => void askSuggestion(q)}
              />
            )}
          </>
        )}

        {step === 'clarify' && (
          <ClarifyStep
            question={question}
            interpretation={interpretation}
            clarifications={clarifications}
            answers={clarificationAnswers}
            onAnswersChange={setClarificationAnswers}
            onEdit={resetToAsk}
            onConfirm={handleConfirmSearch}
            onSkip={handleSkipAndAsk}
            pending={askQuestion.isPending}
            pendingText="Searching the library and generating answer…"
            disabled={clarifyButtonsDisabled}
            disabledTitle={!libraryQAAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
          />
        )}

        {history && history.length > 0 && (
          <QAThread
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: space['3'],
              marginTop: step === 'clarify' ? 0 : space['4'],
            }}
          >
            {history.map((qa) => (
              <LibraryQAExchangeCard key={qa.id} qa={qa} onAskAgain={asksHere(qa.scope) ? askAgain : undefined} />
            ))}
          </QAThread>
        )}
        </QADock>
      </Card>
      )}
    </div>
  );
}

/**
 * T-8.4.2.4: says, beside the composer, that questions here are asked about
 * one source, and offers the way back to the whole library.
 */
function SourceScopeChip({
  source,
  onClear,
  disabled,
}: {
  source: SourceScope;
  onClear: () => void;
  disabled?: boolean;
}) {
  const c = useColors();
  return (
    <div
      role="status"
      data-source-scope=""
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: space['3'],
        flexWrap: 'wrap',
        marginBottom: space['3'],
        padding: `${space['2']} ${space['3']}`,
        background: c.accentSubtle,
        borderRadius: radius.md,
        borderLeft: `3px solid ${c.accent}`,
      }}
    >
      <p
        style={{
          margin: 0,
          minWidth: 0,
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          color: c.textSecondary,
          overflowWrap: 'anywhere',
        }}
      >
        Asking about one source:{' '}
        <strong style={{ color: c.textPrimary, fontWeight: fontWeight.semibold }}>{source.title}</strong>
      </p>
      <Button size="sm" variant="tertiary" onClick={onClear} disabled={disabled}>
        Ask the whole library
      </Button>
    </div>
  );
}
