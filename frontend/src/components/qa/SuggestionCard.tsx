import { useQuery } from '@tanstack/react-query';
import type { MouseEvent } from 'react';
import { useColors } from '../../hooks/useTheme';
import { suggestionsApi, type Suggestion, type SuggestionContext } from '../../services/suggestionsApi';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';

export interface SuggestionCardProps {
  context: SuggestionContext;
  /** Put the question in the composer (a plain click). */
  onFill: (question: string) => void;
  /** Ask it at once (Shift-click). Omit where asking needs the composer first. */
  onAsk?: (question: string) => void;
  /** False while Q&A is down: the card is hidden rather than offering dead actions. */
  enabled?: boolean;
  /** A line under the heading, e.g. where the question will be asked. */
  note?: string;
}

/**
 * "You might ask…" (S-8.4.2, plan M4): three to five next questions under
 * the composer. Loads after the page, never blocks it, and says nothing
 * when there is nothing to suggest. A click fills the composer; Shift-click
 * asks at once. Each use is logged so click-through can be measured.
 */
export function SuggestionCard({ context, onFill, onAsk, enabled = true, note }: SuggestionCardProps) {
  const c = useColors();
  const query = useQuery({
    queryKey: ['suggestions', context],
    queryFn: ({ signal }) => suggestionsApi.get(context, signal),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const items = query.data?.suggestions ?? [];
  if (!enabled || query.isError || (!query.isLoading && items.length === 0)) return null;

  const use = (s: Suggestion, e: MouseEvent) => {
    const ask = e.shiftKey && !!onAsk;
    void suggestionsApi
      .feedback({ context, question: s.question, action: ask ? 'ask' : 'fill', source: s.source })
      .catch(() => undefined);
    if (ask) onAsk!(s.question);
    else onFill(s.question);
  };

  return (
    <section aria-labelledby={`suggest-${context}`} aria-busy={query.isLoading || undefined} style={{ marginTop: space['3'] }}>
      <h3
        id={`suggest-${context}`}
        style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, fontWeight: fontWeight.medium, color: c.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', margin: `0 0 ${space['2']}` }}
      >
        You might ask
      </h3>
      {note && (
        <p style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, margin: `0 0 ${space['2']}` }}>{note}</p>
      )}
      {query.isLoading ? (
        <p style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted, margin: 0 }}>Finding questions worth asking…</p>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
          {items.map((s) => (
            <li key={s.question}>
              <button
                type="button"
                onClick={(e) => use(s, e)}
                title={onAsk ? 'Click to edit it first; Shift-click to ask now' : 'Click to put it in the box'}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  minHeight: 44,
                  padding: `${space['2']} ${space['3']}`,
                  borderRadius: radius.md,
                  border: `1px solid ${c.border}`,
                  background: c.surfaceAlt,
                  cursor: 'pointer',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: space['1'],
                }}
              >
                <span style={{ fontFamily: fonts.body, fontSize: fontSize.base, color: c.textPrimary, lineHeight: lineHeight.snug }}>
                  {s.question}
                </span>
                {(s.rationale || s.source === 'history') && (
                  <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
                    {s.source === 'history' ? 'You asked this before. ' : ''}
                    {s.source === 'history' ? '' : s.rationale}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {onAsk && !query.isLoading && (
        <p style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, margin: `${space['2']} 0 0` }}>
          Click to edit one first, or Shift-click to ask it now.
        </p>
      )}
    </section>
  );
}
