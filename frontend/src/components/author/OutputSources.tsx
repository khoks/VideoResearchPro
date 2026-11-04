/**
 * The sources an Author Studio output cites (S-6.7.3), shown under the
 * manuscript in the reader. Reads `GET /author/outputs/{id}/citations`.
 *
 * One entry per cited source, in the order the output first cites it: its
 * title and channel, then every place the output cites it, as the
 * timestamp link the API recorded (`#n` is the book's endnote number).
 * Citations no library document matched come last under their own label:
 * the API gives them no link, so none is invented.
 *
 * The manuscript carries its own endnotes, so this list is left out of the
 * printed copy (`reader-no-print`).
 */
import { useMemo } from 'react';
import { useColors } from '../../hooks/useTheme';
import { openApiLink } from '../../services/apiFiles';
import type { OutputCitation } from '../../services/authorApi';
import { followableHref, groupCitations } from './citedSources';
import { formatDuration } from '../../utils/formatters';
import { citedFileFailed } from '../citation/citedFile';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../../theme';

function placeLabel(c: OutputCitation): string {
  if (c.seconds != null && c.seconds >= 0) return formatDuration(c.seconds);
  return c.label?.trim() || 'link';
}

export function OutputSources({
  citations,
  isError = false,
}: {
  citations: OutputCitation[] | undefined;
  isError?: boolean;
}) {
  const c = useColors();
  const groups = useMemo(() => groupCitations(citations ?? []), [citations]);

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
    return (
      <section className="reader-no-print" aria-label="Sources" style={frame}>
        <p style={{ margin: 0 }}>The list of sources could not be loaded. The endnotes in the text still name them.</p>
      </section>
    );
  }
  if (groups.length === 0) return null;

  const sourceCount = groups.filter((g) => g.documentId).length;
  const total = citations?.length ?? 0;

  return (
    <section className="reader-no-print output-sources" aria-labelledby="output-sources-title" style={frame}>
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
            <span
              style={{ display: 'flex', flexWrap: 'wrap', gap: space['1'], marginTop: space['1'] }}
              aria-label={`Places cited in ${g.title}`}
            >
              {g.citations.map((cite) => {
                const href = followableHref(cite.url);
                const text = placeLabel(cite);
                const chip = {
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
                    title={`Endnote ${cite.position}`}
                    aria-label={`${text}, endnote ${cite.position}`}
                    onClick={(e) => openApiLink(e, href, citedFileFailed)}
                    onAuxClick={(e) => openApiLink(e, href, citedFileFailed)}
                    style={{ ...chip, color: c.accent, textDecoration: 'none' }}
                  >
                    {text}
                  </a>
                ) : (
                  <span key={cite.position} title={`Endnote ${cite.position}`} style={{ ...chip, color: c.textMuted }}>
                    {text}
                  </span>
                );
              })}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
