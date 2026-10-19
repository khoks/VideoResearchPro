import { useMemo, useState } from 'react';
import { usePasteUrls } from '../../hooks/useLibraryIngest';
import { PASTE_URLS_MAX, type PasteUrlResult } from '../../services/libraryApi';
import {
  detailFromErrorBody,
  guessSourceType,
  parseUrlLines,
  pasteSummaryLine,
  sourceTypeLabel,
  summarizePaste,
  toPasteRowView,
  type HttpErrorLike,
} from '../../utils/ingestResults';
import { Badge, Button, Textarea } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';

interface Props {
  onViewShelf: () => void;
}

export function PasteUrlsForm({ onViewShelf }: Props) {
  const c = useColors();
  const [text, setText] = useState('');
  const [results, setResults] = useState<PasteUrlResult[] | null>(null);
  const paste = usePasteUrls();

  const parsed = useMemo(() => parseUrlLines(text, PASTE_URLS_MAX), [text]);

  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const u of parsed.urls) {
      const t = guessSourceType(u);
      counts.set(t, (counts.get(t) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [parsed.urls]);

  const submit = () => {
    if (parsed.urls.length === 0 || paste.isPending) return;
    paste.mutate(parsed.urls, {
      onSuccess: (resp) => {
        setResults(resp.results);
        setText('');
      },
    });
  };

  const batchError = paste.isError
    ? detailFromErrorBody((paste.error as HttpErrorLike).response?.data) ??
      'The batch was rejected before any URL was processed. Try again.'
    : null;

  const summary = results ? summarizePaste(results) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}
      >
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={6}
          placeholder={'https://example.com/an-essay\nhttps://x.com/someone/status/123\nOne URL per line.'}
          aria-label="URLs to shelve, one per line"
          disabled={paste.isPending}
          style={{ fontFamily: fonts.mono, fontSize: fontSize.sm }}
        />

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: space['3'],
            flexWrap: 'wrap',
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            color: c.textSecondary,
          }}
        >
          <Button type="submit" loading={paste.isPending} disabled={parsed.urls.length === 0}>
            {paste.isPending
              ? 'Fetching…'
              : parsed.urls.length === 0
                ? 'Shelve URLs'
                : `Shelve ${parsed.urls.length} ${parsed.urls.length === 1 ? 'URL' : 'URLs'}`}
          </Button>
          {parsed.urls.length > 0 && (
            <span style={{ display: 'inline-flex', gap: space['2'], flexWrap: 'wrap', alignItems: 'center' }}>
              {typeCounts.map(([type, n]) => (
                <Badge key={type} tone="neutral" size="sm">
                  {n} × {sourceTypeLabel(type)}
                </Badge>
              ))}
            </span>
          )}
          {(parsed.duplicatesDropped > 0 || parsed.overCapDropped > 0) && (
            <span style={{ color: c.textMuted, fontSize: fontSize.xs }}>
              {parsed.duplicatesDropped > 0 && `${parsed.duplicatesDropped} duplicate line${parsed.duplicatesDropped === 1 ? '' : 's'} ignored`}
              {parsed.duplicatesDropped > 0 && parsed.overCapDropped > 0 && ' · '}
              {parsed.overCapDropped > 0 && `only the first ${PASTE_URLS_MAX} will be sent`}
            </span>
          )}
        </div>

        <p
          style={{
            margin: 0,
            fontFamily: fonts.body,
            fontSize: fontSize.sm,
            color: c.textMuted,
            lineHeight: lineHeight.normal,
          }}
        >
          Facebook, Instagram, LinkedIn and X links are shelved as posts; everything else as an
          article. Each page is fetched and extracted in turn, so large batches take a while and
          the button stays busy until the whole batch is back.
        </p>
      </form>

      {batchError && (
        <div
          role="alert"
          style={{
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            color: c.error,
            background: c.errorSubtle,
            border: `1px solid ${c.error}`,
            borderRadius: radius.md,
            padding: `${space['2']} ${space['3']}`,
          }}
        >
          {batchError}
        </div>
      )}

      {results && summary && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
            <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.textPrimary }}>
              {pasteSummaryLine(summary)}
            </span>
            {summary.created + summary.deduped > 0 && (
              <Button size="sm" variant="tertiary" onClick={onViewShelf} trailingIcon={<span aria-hidden>→</span>}>
                See them on the shelf
              </Button>
            )}
            <Button size="sm" variant="tertiary" onClick={() => setResults(null)}>
              Clear
            </Button>
          </div>
          <PasteResultsTable results={results} />
        </div>
      )}
    </div>
  );
}

function PasteResultsTable({ results }: { results: PasteUrlResult[] }) {
  const c = useColors();
  const rows = results.map(toPasteRowView);
  const cell: React.CSSProperties = {
    padding: `${space['2']} ${space['3']}`,
    borderTop: `1px solid ${c.border}`,
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    color: c.textPrimary,
    verticalAlign: 'top',
  };
  const head: React.CSSProperties = {
    ...cell,
    borderTop: 'none',
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    color: c.textMuted,
    textAlign: 'left',
  };

  return (
    <div style={{ overflowX: 'auto', border: `1px solid ${c.border}`, borderRadius: radius.md, background: c.surface }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={head}>URL</th>
            <th style={head}>Type</th>
            <th style={{ ...head, textAlign: 'right' }}>Words</th>
            <th style={head}>Result</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.url}-${i}`}>
              <td style={{ ...cell, maxWidth: 360 }}>
                <a
                  href={r.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={r.url}
                  style={{
                    color: c.accent,
                    textDecoration: 'none',
                    display: 'block',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    fontFamily: fonts.mono,
                    fontSize: fontSize.xs,
                  }}
                >
                  {r.url}
                </a>
              </td>
              <td style={{ ...cell, whiteSpace: 'nowrap' }}>
                {sourceTypeLabel(r.sourceType)}
                {r.typeGuessed && (
                  <span title="Detected locally; the server did not report a type for this row." style={{ color: c.textMuted }}>
                    {' '}
                    ?
                  </span>
                )}
              </td>
              <td style={{ ...cell, textAlign: 'right', fontFamily: fonts.mono, fontSize: fontSize.xs, color: c.textSecondary }}>
                {r.wordCount === null ? '—' : r.wordCount.toLocaleString()}
              </td>
              <td style={cell}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: space['1'] }}>
                  <span>
                    <Badge tone={r.presentation.tone} size="sm">
                      {r.presentation.label}
                    </Badge>
                  </span>
                  <span style={{ fontSize: fontSize.xs, color: c.textSecondary, lineHeight: lineHeight.snug }}>
                    {r.presentation.detail}
                  </span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
