/**
 * The sources an Author Studio output cites (S-6.7.3), shown under the
 * manuscript in the reader. Reads `GET /author/outputs/{id}/citations`.
 *
 * One entry per cited source, in the order the output first cites it: its
 * title and channel, then every place the output cites it, as the
 * timestamp link the API recorded. Citations no library document matched come
 * last under their own label. An unmatched absolute link keeps its URL and
 * stays a link; an unmatched bare anchor has none, so none is invented.
 *
 * Every output kind records citations, but only a book's text numbers them:
 * its endnote `n` is `position` `n`. A deck's footnotes number documents while
 * the API has one row per cited moment, and a site's contents and a newsletter
 * have no footnotes, so only a book names endnotes here.
 *
 * Print goes by what the text itself carries. A book's endnotes and a deck's
 * sources list every cited moment, so the list stays off paper
 * (`reader-no-print`). A site's contents name only documents and a newsletter's
 * links lose their target on paper, so there the list prints.
 */
import { useMemo } from 'react';
import { useColors } from '../../hooks/useTheme';
import { openApiLink } from '../../services/apiFiles';
import type { OutputCitation } from '../../services/authorApi';
import { followableHref, groupCitations } from './citedSources';
import { formatDuration } from '../../utils/formatters';
import { citedFileFailed } from '../citation/citedFile';
import { inlineErrorMessage } from '../../utils/apiError';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../../theme';

function placeLabel(c: OutputCitation): string {
  if (c.seconds != null && c.seconds >= 0) return formatDuration(c.seconds);
  return c.label?.trim() || 'link';
}

export function OutputSources({
  citations,
  kind,
  isError = false,
  error,
}: {
  citations: OutputCitation[] | undefined;
  /** The output's kind: `book`, `deck`, `site` or `newsletter`. */
  kind: string;
  isError?: boolean;
  /** The failed read, whose words the line says (T-3.4.1.26). */
  error?: unknown;
}) {
  const c = useColors();
  const groups = useMemo(() => groupCitations(citations ?? []), [citations]);
  const hasEndnotes = kind === 'book';
  const textCarriesCitations = hasEndnotes || kind === 'deck';

  const frame = {
    maxWidth: measure.reading,
    marginTop: space['8'],
    paddingTop: space['5'],
    borderTop: `1px solid ${c.border}`,
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    lineHeight: lineHeight.snug,
    color: c.textSecondary,
  } as const;

  if (isError) {
    // The one place the failure is said: the hook sets `meta`. Nothing for a 401.
    const failure = inlineErrorMessage(error, 'The list of sources could not be loaded.');
    if (!failure) return null;
    return (
      <section className="reader-no-print" aria-label="Sources" style={frame}>
        <p role="alert" style={{ margin: 0 }}>
          {failure}
          {hasEndnotes && ' The endnotes in the text still name them.'}
        </p>
      </section>
    );
  }
  if (groups.length === 0) return null;

  const sourceCount = groups.filter((g) => g.documentId).length;
  const total = citations?.length ?? 0;

  return (
    <section
      className={textCarriesCitations ? 'reader-no-print' : undefined}
      aria-labelledby="output-sources-title"
      style={frame}
    >
      <h2
        style={{
          margin: `0 0 ${space['3']}`,
          fontFamily: fonts.display,
          fontSize: fontSize.lg,
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
        }}
      >
        <span id="output-sources-title">Sources</span>{' '}
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted, fontWeight: fontWeight.regular }}>
          · {sourceCount} {sourceCount === 1 ? 'source' : 'sources'}, {total} {total === 1 ? 'citation' : 'citations'}
        </span>
      </h2>
      <ol style={{ margin: 0, paddingLeft: space['6'] }}>
        {groups.map((g) => (
          <li key={g.documentId ?? 'unmatched'} style={{ marginBottom: space['3'] }}>
            <span style={{ color: g.documentId ? c.textPrimary : c.textMuted, fontWeight: fontWeight.medium }}>
              {g.title}
            </span>
            {g.channel && <span> — {g.channel}</span>}
            <div
              role="group"
              aria-label={`Places cited: ${g.title}`}
              style={{ display: 'flex', flexWrap: 'wrap', gap: space['1'], marginTop: space['1'] }}
            >
              {g.citations.map((cite) => {
                const href = followableHref(cite.url);
                const text = placeLabel(cite);
                const chip = {
                  display: 'inline-flex',
                  alignItems: 'center',
                  minHeight: 24,
                  fontFamily: fonts.mono,
                  fontSize: fontSize.xs,
                  padding: `1px ${space['2']}`,
                  borderRadius: radius.pill,
                  border: `1px solid ${c.border}`,
                  background: c.surfaceAlt,
                } as const;
                return href ? (
                  <a
                    key={cite.position}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={hasEndnotes ? `Endnote ${cite.position}` : undefined}
                    aria-label={hasEndnotes ? `${text}, endnote ${cite.position}` : undefined}
                    onClick={(e) => openApiLink(e, href, citedFileFailed)}
                    onAuxClick={(e) => openApiLink(e, href, citedFileFailed)}
                    style={{ ...chip, color: c.accent, textDecoration: 'none' }}
                  >
                    {text}
                  </a>
                ) : (
                  <span
                    key={cite.position}
                    title={hasEndnotes ? `Endnote ${cite.position}` : undefined}
                    style={{ ...chip, color: c.textMuted }}
                  >
                    {text}
                  </span>
                );
              })}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
