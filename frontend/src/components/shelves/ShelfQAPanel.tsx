/**
 * Ask this shelf (S-8.1.4): the library Q&A, answered only from the sources of
 * the runs on the shelf. An empty shelf has nothing to ask, so the composer
 * says so instead of returning "no sources". Answers also join the library
 * Q&A history, where they say which shelf they were asked on.
 */
import { useState, type FormEvent } from 'react';
import { Button, Card, FormField, Select, Textarea } from '../primitives';
import { InfoStripe, LibraryQAExchangeCard } from '../qa/LibraryQAExchangeCard';
import { useAskShelf, useShelfHasSources, useShelfQuestions } from '../../hooks/useShelves';
import { useFeatureAvailable } from '../../hooks/useFeatureAvailable';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../../theme';
import type { AnswerLanguage } from '../../types/qa';

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
  const available = useFeatureAvailable('library_qa');
  const [question, setQuestion] = useState('');
  const [language, setLanguage] = useState<AnswerLanguage>('en');

  const empty = hasSources.isSuccess && !hasSources.data;
  const disabled = !available || empty || ask.isPending;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || disabled) return;
    try {
      await ask.mutateAsync({ question: q, answer_language: language });
      setQuestion('');
    } catch {
      // the global mutation cache already toasted; keep the question to retry
    }
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
        ) : (
          <form onSubmit={onSubmit}>
            <FormField label="Your question">
              {(controlId) => (
                <Textarea
                  id={controlId}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void onSubmit(e);
                  }}
                  rows={3}
                  placeholder={`What do the sources on ${shelfName} say about…`}
                  disabled={!available || ask.isPending}
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
              <FormField label="Answer in">
                {(controlId) => (
                  <Select
                    id={controlId}
                    value={language}
                    onChange={(e) => setLanguage(e.target.value as AnswerLanguage)}
                    style={{ width: 'auto', minWidth: 140 }}
                  >
                    {LANGUAGE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </Select>
                )}
              </FormField>
              <Button
                type="submit"
                disabled={disabled || !question.trim()}
                loading={ask.isPending}
                title={!available ? 'LLM-dependent feature is temporarily unavailable' : undefined}
              >
                Ask this shelf
              </Button>
            </div>
          </form>
        )}

        {ask.isPending && (
          <div style={{ marginTop: space['3'] }}>
            <InfoStripe text="Searching this shelf and writing the answer…" />
          </div>
        )}

        {history.data && history.data.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'], marginTop: space['4'] }}>
            {history.data.map((qa) => (
              <LibraryQAExchangeCard key={qa.id} qa={qa} showScope={false} />
            ))}
          </div>
        )}
      </Card>
    </section>
  );
}
