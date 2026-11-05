/**
 * Ask this shelf (S-8.1.4): the library Q&A, answered only from the sources of
 * the runs on the shelf. An empty shelf has nothing to ask, so the composer
 * says so instead of returning "no sources". Answers also join the library
 * Q&A history, where they say which shelf they were asked on.
 *
 * S-8.13.2: a question goes through the library page's clarify step first.
 * That call sends the question and nothing about the shelf, so it needs no
 * shelf route; the ask that follows is the one scoped to the shelf. The step
 * is optional: when it fails the question goes straight to the shelf, because
 * a clarify outage must not stop an ask that does not need it.
 *
 * T-1.15.4.6: the job and library panels' depth control, sent the same way: the
 * request carries `output_length` only when a depth shows, and a pick is for one
 * ask (D-125). It starts from the account's default depth (T-1.15.3.9).
 *
 * `ShelfPage` keys this panel on the shelf, so all of this state is one shelf's.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Button, Card, FormField, Select, Textarea } from '../primitives';
import { DepthSelect } from '../common/DepthSelect';
import { ClarifyStep } from '../qa/ClarifyStep';
import { InfoStripe, LibraryQAExchangeCard } from '../qa/LibraryQAExchangeCard';
import { useAskShelf, useShelfHasSources, useShelfQuestions } from '../../hooks/useShelves';
import { useClarifyLibraryQA } from '../../hooks/useLibraryQA';
import { useDepthChoice } from '../../hooks/useDepthChoice';
import { useFeatureAvailable } from '../../hooks/useFeatureAvailable';
import { usePreferredDepth } from '../../hooks/useMe';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../../theme';
import type { AnswerLanguage } from '../../types/qa';
import { buildClarifyContext } from '../../utils/clarifyContext';
import { withDepth } from '../../utils/depth';

const LANGUAGE_OPTIONS: Array<{ value: AnswerLanguage; label: string }> = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'हिन्दी' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
];

export function ShelfQAPanel({ shelfId, shelfName }: { shelfId: string; shelfName: string }) {
  const c = useColors();
  const history = useShelfQuestions(shelfId);
  const hasSources = useShelfHasSources(shelfId);
  const ask = useAskShelf(shelfId);
  const clarify = useClarifyLibraryQA();
  const available = useFeatureAvailable('library_qa');
  const [question, setQuestion] = useState('');
  const [language, setLanguage] = useState<AnswerLanguage>('en');
  const { depth, pick: setDepth, reset: resetDepth } = useDepthChoice(usePreferredDepth());
  const [step, setStep] = useState<'ask' | 'clarify'>('ask');
  const [interpretation, setInterpretation] = useState('');
  const [clarifications, setClarifications] = useState<string[]>([]);
  const [answers, setAnswers] = useState<string[]>([]);
  const mounted = useRef(false);
  const questionInput = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const empty = hasSources.isSuccess && !hasSources.data;
  const disabled = !available || empty || ask.isPending || clarify.isPending;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || disabled) return;
    try {
      const result = await clarify.mutateAsync({ question: q });
      setInterpretation(result.interpretation);
      setClarifications(result.clarifications);
      setAnswers(new Array(result.clarifications.length).fill(''));
      setStep('clarify');
    } catch {
      // The global mutation cache already toasted the clarify failure. A panel
      // the reader has left asks nothing: that call settled after they moved on.
      if (mounted.current) await send();
    }
  };

  const send = async (context?: string) => {
    const body = { question: question.trim(), answer_language: language };
    try {
      await ask.mutateAsync(withDepth(context ? { ...body, context } : body, depth));
      setQuestion('');
      setStep('ask');
      resetDepth();
    } catch {
      // toasted as above; the step stays, with what the reader typed into it
    }
  };

  // T-1.15.4.5: a cut-off answer's offer; see `AnswerCutOffNote`.
  const askAtDeep = (q: string) => {
    setStep('ask');
    setQuestion(q);
    setDepth('deep');
    setTimeout(() => questionInput.current?.focus(), 0);
  };

  return (
    <section aria-labelledby="shelf-qa-heading" style={{ marginBottom: space['6'] }} data-shelf-qa="">
      <h2
        id="shelf-qa-heading"
        style={{
          fontFamily: fonts.display,
          fontSize: fontSize.lg,
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
          margin: `0 0 ${space['1']}`,
        }}
      >
        Ask this shelf
      </h2>
      <p
        style={{
          margin: `0 0 ${space['3']}`,
          fontFamily: fonts.body,
          fontSize: fontSize.sm,
          color: c.textSecondary,
          lineHeight: lineHeight.snug,
          maxWidth: measure.reading,
        }}
      >
        Answers draw only on the sources of the runs on {shelfName}, never the rest of your library.
      </p>
      <Card>
        {empty ? (
          <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary }}>
            This shelf has no sources yet, so there is nothing to ask. Add a run that found sources, then ask here.
          </p>
        ) : step === 'clarify' ? (
          <ClarifyStep
            question={question.trim()}
            interpretation={interpretation}
            clarifications={clarifications}
            answers={answers}
            onAnswersChange={setAnswers}
            onEdit={() => setStep('ask')}
            onConfirm={() => void send(buildClarifyContext(interpretation, clarifications, answers))}
            onSkip={() => void send()}
            pending={ask.isPending}
            pendingText="Searching this shelf and writing the answer…"
            disabled={!available || ask.isPending}
            disabledTitle={!available ? 'LLM-dependent feature is temporarily unavailable' : undefined}
          />
        ) : (
          <form onSubmit={onSubmit}>
            <FormField label="Your question">
              {(controlId) => (
                <Textarea
                  ref={questionInput}
                  id={controlId}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void onSubmit(e);
                  }}
                  rows={3}
                  placeholder={`What do the sources on ${shelfName} say about…`}
                  disabled={!available || clarify.isPending || ask.isPending}
                />
              )}
            </FormField>
            <div
              style={{
                display: 'flex',
                alignItems: 'flex-end',
                justifyContent: 'space-between',
                gap: space['3'],
                flexWrap: 'wrap',
                marginTop: space['3'],
              }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: space['3'], flexWrap: 'wrap' }}>
                <FormField label="Answer in">
                  {(controlId) => (
                    <Select
                      id={controlId}
                      value={language}
                      onChange={(e) => setLanguage(e.target.value as AnswerLanguage)}
                      style={{ width: 'auto', minWidth: 140 }}
                      disabled={ask.isPending || clarify.isPending}
                    >
                      {LANGUAGE_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </Select>
                  )}
                </FormField>
                <FormField label="Answer depth">
                  {(controlId) => (
                    <DepthSelect
                      id={controlId}
                      value={depth}
                      onChange={setDepth}
                      unsetLabel="Default"
                      title="Default: sized to how many sources this shelf holds."
                      disabled={ask.isPending || clarify.isPending}
                    />
                  )}
                </FormField>
              </div>
              <Button
                type="submit"
                disabled={disabled || !question.trim()}
                loading={clarify.isPending || ask.isPending}
                title={!available ? 'LLM-dependent feature is temporarily unavailable' : undefined}
              >
                Ask this shelf
              </Button>
            </div>
          </form>
        )}

        {clarify.isPending && (
          <div style={{ marginTop: space['3'] }}>
            <InfoStripe text="Listening for the echo of your question…" />
          </div>
        )}

        {ask.isPending && step === 'ask' && (
          <div style={{ marginTop: space['3'] }}>
            <InfoStripe text="Searching this shelf and writing the answer…" />
          </div>
        )}

        {history.data && history.data.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'], marginTop: space['4'] }}>
            {history.data.map((qa) => (
              <LibraryQAExchangeCard
                key={qa.id}
                qa={qa}
                showScope={false}
                onAskAgain={available && !ask.isPending && !clarify.isPending ? askAtDeep : undefined}
              />
            ))}
          </div>
        )}
      </Card>
    </section>
  );
}
