/**
 * `/knowledge/:videoId` — a source's knowledge report in the reading room
 * (S-8.8.3). Same shell as reports: outline from the Markdown's own
 * headings, drop cap, progress, print. The drawer on the job page stays as a
 * quick peek and links here.
 *
 * `videoId` may be the YouTube id or the `document_id`; the backend resolves
 * either, through the tenant's visibility grants.
 */
import { useEffect, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useKnowledge } from '../hooks/useKnowledge';
import { Button, EmptyState, Spinner } from '../components/primitives';
import { ReaderShell, StatTiles, describeSource, formatPublished, parseMarkdownDoc } from '../components/reader';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, space } from '../theme';

export function KnowledgeReaderPage() {
  const { videoId } = useParams<{ videoId: string }>();
  const navigate = useNavigate();
  const c = useColors();
  const { data, isLoading, error } = useKnowledge(videoId ?? null);

  const parsed = useMemo(
    () => (data?.knowledge_report_md ? parseMarkdownDoc(data.knowledge_report_md, { title: data.title }) : null),
    [data],
  );
  const title = parsed?.docTitle || data?.title || 'Knowledge report';

  useEffect(() => {
    if (!parsed) return;
    const previous = document.title;
    document.title = `${title} · Pratidhvani`;
    return () => {
      document.title = previous;
    };
  }, [parsed, title]);

  const back = (
    <Button size="sm" variant="tertiary" onClick={() => navigate(-1)}>
      ← Back
    </Button>
  );

  if (isLoading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], color: c.textSecondary }}>
        <Spinner /> <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm }}>Opening the knowledge report…</span>
      </div>
    );
  }

  if (error) {
    return (
      <EmptyState
        title="The knowledge report could not be opened"
        description={error instanceof Error ? error.message : 'Something went wrong while loading it.'}
        action={back}
      />
    );
  }

  if (!data || !parsed) {
    return (
      <EmptyState
        title="No knowledge report for this source yet"
        description="Generate one from the source's row on its run page; it opens here once extraction finishes."
        action={back}
      />
    );
  }

  const source = data.title
    ? {
        document_id: data.document_id ?? null,
        video_id: data.video_id ?? null,
        source_type: data.source_type,
        title: data.title,
        channel_name: data.channel_name ?? '',
        url: data.url ?? '',
        source_url: null,
        duration_seconds: null,
        published_at: data.published_at ?? null,
        thumbnail_url: null,
        source_metadata: {},
      }
    : null;
  const desc = source ? describeSource(source) : null;
  const extracted = formatPublished(data.knowledge_extracted_at);
  const meta = [
    source && source.title !== title ? `From ${source.title}` : null,
    desc?.meta[0] ?? null,
    extracted ? `Extracted ${extracted}` : null,
  ].filter(Boolean);

  return (
    <ReaderShell
      kicker={desc ? `Knowledge report · ${desc.kind}` : 'Knowledge report'}
      title={title}
      meta={meta.length ? meta.join(' · ') : null}
      actions={
        <>
          {back}
          {data.url && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => window.open(data.url!, '_blank', 'noopener,noreferrer')}
            >
              Open the source ↗
            </Button>
          )}
          <Button size="sm" variant="secondary" onClick={() => window.print()}>
            Print or save as PDF
          </Button>
        </>
      }
      outline={parsed.outline}
      before={
        <StatTiles
          label="What was extracted"
          tiles={[
            { label: 'Topics', value: data.topics.length },
            { label: 'Concepts', value: data.concepts.length },
            { label: 'Events', value: data.events.length },
            { label: 'Facts', value: data.facts.length },
          ]}
        />
      }
    >
      {parsed.content}
    </ReaderShell>
  );
}
