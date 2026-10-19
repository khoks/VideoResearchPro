/**
 * `/reports/:jobId` — the reading room for a run's report (S-8.8.1).
 *
 * Fetches `{title, html, statistics}` with the bearer header (no token in any
 * URL), sanitises the HTML, parses it into React with heading ids, an outline
 * and citation chips, and renders through `ReaderShell`. The iframe modal on
 * the job page survives as a quick peek and still owns "Open in new tab".
 */
import { useEffect, useMemo, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useReportBody } from '../hooks/useReport';
import { Button, EmptyState, Spinner } from '../components/primitives';
import { ReaderCitation, ReaderShell, parseReportHtml, sanitizeReportHtml } from '../components/reader';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../theme';
import type { ReportStatistics } from '../types/report';

const KICKER: Record<string, string> = {
  topic: 'Research report',
  channel: 'Channel report',
  subscription: 'Report',
};

export function ReportReaderPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const c = useColors();
  const { data: body, isLoading, error } = useReportBody(jobId ?? null);

  const parsed = useMemo(() => {
    if (!body) return null;
    return parseReportHtml(sanitizeReportHtml(body.html), {
      title: body.title,
      renderCitation: (citation) => <ReaderCitation key={citation.index} citation={citation} />,
    });
  }, [body]);

  useEffect(() => {
    if (!body) return;
    const previous = document.title;
    document.title = `${body.title} · Pratidhvani`;
    return () => {
      document.title = previous;
    };
  }, [body]);

  const backToRun = (
    <Button size="sm" variant="tertiary" onClick={() => navigate(`/jobs/${jobId}`)}>
      ← Back to the run
    </Button>
  );

  if (isLoading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], color: c.textSecondary }}>
        <Spinner /> <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm }}>Opening the report…</span>
      </div>
    );
  }

  if (error || !body || !parsed) {
    const status = error?.response?.status;
    return (
      <EmptyState
        title={status === 404 ? 'No report for this run yet' : 'The report could not be opened'}
        description={
          status === 404
            ? 'Reports appear here once a topic or channel run has finished writing one.'
            : (error?.response?.data?.detail ?? error?.message ?? 'Something went wrong while loading it.')
        }
        action={backToRun}
      />
    );
  }

  const meta = formatMeta(body.generated_at, body.statistics);

  return (
    <ReaderShell
      kicker={KICKER[body.job_type] ?? 'Report'}
      title={body.title}
      meta={meta}
      actions={backToRun}
      outline={parsed.outline}
      before={body.statistics ? <StatisticsTiles statistics={body.statistics} /> : null}
    >
      {parsed.content}
    </ReaderShell>
  );
}

function formatMeta(generatedAt: string | null, stats: ReportStatistics | null): ReactNode {
  const parts: string[] = [];
  if (generatedAt) parts.push(`Generated ${generatedAt}`);
  if (stats?.video_count != null) parts.push(`${stats.video_count} ${stats.video_count === 1 ? 'source' : 'sources'}`);
  if (stats?.total_words != null) parts.push(`${stats.total_words.toLocaleString()} transcript words`);
  if (stats?.total_minutes != null) parts.push(`${stats.total_minutes.toLocaleString()} minutes of audio`);
  return parts.length ? parts.join(' · ') : null;
}

function StatisticsTiles({ statistics }: { statistics: ReportStatistics }) {
  const c = useColors();
  const tiles: Array<{ label: string; value: number | null }> = [
    { label: 'Sources', value: statistics.video_count },
    { label: 'Transcripts', value: statistics.transcript_count },
    { label: 'Words', value: statistics.total_words },
    { label: 'Minutes', value: statistics.total_minutes },
  ].filter((t) => t.value != null);
  if (tiles.length === 0) return null;
  return (
    <dl
      aria-label="Corpus statistics"
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: space['3'],
        margin: `0 0 ${space['6']}`,
        maxWidth: measure.reading,
      }}
    >
      {tiles.map((t) => (
        <div
          key={t.label}
          style={{
            flex: '1 1 120px',
            padding: `${space['2']} ${space['3']}`,
            background: c.surfaceAlt,
            borderRadius: radius.md,
            fontFamily: fonts.ui,
          }}
        >
          <dt
            style={{
              fontSize: fontSize.xs,
              fontWeight: fontWeight.medium,
              color: c.textMuted,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
            }}
          >
            {t.label}
          </dt>
          <dd
            style={{
              margin: 0,
              fontFamily: fonts.display,
              fontSize: fontSize.lg,
              fontWeight: fontWeight.semibold,
              lineHeight: lineHeight.tight,
              color: c.textPrimary,
            }}
          >
            {t.value!.toLocaleString()}
          </dd>
        </div>
      ))}
    </dl>
  );
}
