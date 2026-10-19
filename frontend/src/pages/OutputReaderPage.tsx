/**
 * `/author/outputs/:outputId` — an Author Studio output in the reading room
 * (S-8.8.3). Books are Markdown manuscripts; they get the same outline,
 * measure, drop cap, progress and print as reports. Replaces the Author
 * page's own viewer modal (T-6.1.1.3's "View opens the shared reader").
 */
import { useEffect, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuthorOutput, useAuthorOutputContent } from '../hooks/useAuthor';
import { Button, EmptyState, Spinner } from '../components/primitives';
import { ReaderShell, StatTiles, formatPublished, parseMarkdownDoc } from '../components/reader';
import { useColors } from '../hooks/useTheme';
import { useJobStore } from '../stores/jobStore';
import { downloadUrl } from '../utils/download';
import { kindMeta, outputDownloadFilename, outputMediaType, outputStatusLabel } from '../utils/authorOutputs';
import { fonts, fontSize, space } from '../theme';

function httpStatus(err: unknown): number | undefined {
  return (err as { response?: { status?: number } } | null)?.response?.status;
}

function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

export function OutputReaderPage() {
  const { outputId } = useParams<{ outputId: string }>();
  const navigate = useNavigate();
  const c = useColors();
  const pushToast = useJobStore((s) => s.pushToast);
  const output = useAuthorOutput(outputId ?? null);
  const readable = output.data?.status === 'completed' && output.data.has_content;
  const content = useAuthorOutputContent(readable ? (outputId ?? null) : null);

  const parsed = useMemo(
    () => (content.data ? parseMarkdownDoc(content.data, { title: output.data?.title }) : null),
    [content.data, output.data?.title],
  );

  useEffect(() => {
    if (!output.data || !parsed) return;
    const previous = document.title;
    document.title = `${output.data.title} · Pratidhvani`;
    return () => {
      document.title = previous;
    };
  }, [output.data, parsed]);

  const back = (
    <Button size="sm" variant="tertiary" onClick={() => navigate('/author')}>
      ← Author Studio
    </Button>
  );

  if (output.isLoading || content.isLoading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], color: c.textSecondary }}>
        <Spinner /> <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm }}>Opening the manuscript…</span>
      </div>
    );
  }

  const err = output.error ?? content.error;
  if (err || !output.data) {
    const status = httpStatus(err);
    return (
      <EmptyState
        title={
          status === 403
            ? 'Author Studio is not on your plan'
            : status === 404
              ? 'This output does not exist'
              : 'The output could not be opened'
        }
        description={
          status === 403
            ? 'Books and the other Author Studio outputs come with the Pro and Studio tiers.'
            : status === 404
              ? 'It may have been deleted, or it belongs to another account.'
              : 'Something went wrong while loading it.'
        }
        action={back}
      />
    );
  }

  const item = output.data;
  if (!readable || !parsed || content.data == null) {
    return (
      <EmptyState
        title={`${item.title} is not ready to read`}
        description={
          item.status === 'failed'
            ? (item.error_message ?? 'Generation failed.')
            : `Its status is “${outputStatusLabel(item.status)}”. It opens here once it has content.`
        }
        action={back}
      />
    );
  }

  const download = () => {
    try {
      const url = URL.createObjectURL(new Blob([content.data!], { type: outputMediaType(item) }));
      downloadUrl(url, outputDownloadFilename(item));
      window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
    } catch {
      pushToast('error', 'Could not prepare the download.');
    }
  };

  const chapters = parsed.outline.filter((o) => o.level === 2).length;
  const created = formatPublished(item.created_at);

  return (
    <ReaderShell
      kicker={kindMeta(item.kind).label}
      title={item.title}
      meta={created ? `Compiled ${created} by Author Studio` : null}
      actions={
        <>
          {back}
          <Button size="sm" variant="secondary" onClick={download}>
            Download
          </Button>
          <Button size="sm" variant="secondary" onClick={() => window.print()}>
            Print or save as PDF
          </Button>
        </>
      }
      outline={parsed.outline}
      before={
        <StatTiles
          label="Manuscript"
          tiles={[
            { label: 'Sources', value: item.source_ids.length },
            { label: 'Sections', value: chapters },
            { label: 'Words', value: wordCount(content.data) },
          ]}
        />
      }
    >
      {parsed.content}
    </ReaderShell>
  );
}
