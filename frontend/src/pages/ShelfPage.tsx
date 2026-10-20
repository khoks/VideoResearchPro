import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  useRemoveJobFromShelf,
  useShelf,
  useShelfDocumentsFetcher,
  useUpdateShelf,
  shelvesKeys,
} from '../hooks/useShelves';
import { useTierCapabilities } from '../hooks/useTierCapabilities';
import { DocumentsBrowser } from '../components/library/DocumentsBrowser';
import { ShelfQAPanel } from '../components/shelves/ShelfQAPanel';
import {
  DeleteShelfModal,
  ShelfDot,
  ShelfFormModal,
  type ShelfFormValues,
} from '../components/shelves';
import {
  Button,
  Card,
  EmptyState,
  Skeleton,
  StatusPill,
} from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../theme';
import { formatDate } from '../utils/formatters';
import { isNotFound } from '../utils/apiError';
import { jobDisplayTitle, jobTypeLabel } from '../utils/jobTitle';
import type { ShelfDetail } from '../services/shelvesApi';
import type { Job } from '../types/job';

/**
 * `/shelves/:shelfId` (S-8.1.2) — one shelf: its runs, and the union of their
 * documents as a filtered library view (deduplicated and visibility-scoped
 * by `GET /shelves/{id}/documents`). The shelf-scoped question box arrives
 * with S-8.1.4.
 */
export function ShelfPage() {
  const { shelfId = '' } = useParams<{ shelfId: string }>();
  const navigate = useNavigate();
  const c = useColors();
  const { has } = useTierCapabilities();
  const canWrite = has('shelves');

  const shelfQuery = useShelf(shelfId || null);
  const update = useUpdateShelf();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const shelf = shelfQuery.data;

  const initial = useMemo(
    () => (shelf ? { name: shelf.name, description: shelf.description, color: shelf.color } : null),
    [shelf],
  );

  const back = (
    <nav aria-label="Breadcrumb" style={{ marginBottom: space['3'] }}>
      <Link
        to="/shelves"
        style={{
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          fontWeight: fontWeight.medium,
          color: c.textSecondary,
          textDecoration: 'none',
        }}
      >
        ← Shelves
      </Link>
    </nav>
  );

  if (shelfQuery.isLoading) {
    return (
      <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
        {back}
        <div aria-busy style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          <Skeleton width={64} height={12} />
          <Skeleton width="40%" height={32} />
          <Skeleton width="30%" height={14} />
        </div>
      </div>
    );
  }

  if (shelfQuery.isError || !shelf) {
    const missing = isNotFound(shelfQuery.error);
    return (
      <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
        {back}
        <EmptyState
          title={missing ? "This shelf isn't here." : "Couldn't load this shelf."}
          description={
            missing
              ? 'It may have been deleted, or the link is stale.'
              : 'Something blocked the fetch. Try again in a moment.'
          }
          action={
            missing ? (
              <Button variant="secondary" onClick={() => navigate('/shelves')}>
                All shelves
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => void shelfQuery.refetch()}>
                Retry
              </Button>
            )
          }
        />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
      {back}

      <header
        style={{
          marginBottom: space['5'],
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: space['4'],
          flexWrap: 'wrap',
        }}
      >
        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <p
            style={{
              margin: `0 0 ${space['1']}`,
              fontFamily: fonts.ui,
              fontSize: fontSize.xs,
              fontWeight: fontWeight.semibold,
              color: c.textMuted,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              display: 'flex',
              alignItems: 'center',
              gap: space['2'],
            }}
          >
            <ShelfDot color={shelf.color} />
            Shelf
          </p>
          <h1
            style={{
              fontFamily: fonts.display,
              fontSize: fontSize['2xl'],
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
              margin: 0,
              lineHeight: lineHeight.tight,
              overflowWrap: 'anywhere',
            }}
          >
            {shelf.name}
          </h1>
          {shelf.description && (
            <p
              style={{
                margin: `${space['2']} 0 0`,
                fontFamily: fonts.body,
                fontSize: fontSize.base,
                color: c.textSecondary,
                maxWidth: measure.reading,
              }}
            >
              {shelf.description}
            </p>
          )}
          <p
            style={{
              margin: `${space['2']} 0 0`,
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              color: c.textMuted,
            }}
          >
            {shelf.job_count} {shelf.job_count === 1 ? 'run' : 'runs'} · updated{' '}
            {formatDate(shelf.updated_at)}
            {!canWrite && ' · read-only on your plan'}
          </p>
        </div>
        {canWrite && (
          <div style={{ display: 'flex', gap: space['2'], flexShrink: 0 }}>
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
              Edit
            </Button>
            <Button size="sm" variant="tertiary" onClick={() => setDeleting(true)}>
              Delete
            </Button>
          </div>
        )}
      </header>

      <ShelfRuns shelf={shelf} canWrite={canWrite} />

      <ShelfQAPanel shelfId={shelf.id} shelfName={shelf.name} />

      <ShelfDocuments shelfId={shelf.id} />

      <ShelfFormModal
        open={editing}
        onClose={() => setEditing(false)}
        title="Edit shelf"
        submitLabel="Save"
        initial={initial}
        onSubmit={(v: ShelfFormValues) => update.mutateAsync({ id: shelf.id, body: v })}
      />
      <DeleteShelfModal
        shelf={deleting ? shelf : null}
        onClose={() => setDeleting(false)}
        onDeleted={() => navigate('/shelves')}
      />
    </div>
  );
}

function ShelfRuns({ shelf, canWrite }: { shelf: ShelfDetail; canWrite: boolean }) {
  const c = useColors();
  const navigate = useNavigate();
  const remove = useRemoveJobFromShelf();

  return (
    <section aria-labelledby="shelf-runs-heading" style={{ marginBottom: space['6'] }}>
      <h2
        id="shelf-runs-heading"
        style={{
          fontFamily: fonts.display,
          fontSize: fontSize.lg,
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
          margin: `0 0 ${space['3']}`,
        }}
      >
        Runs
      </h2>
      {shelf.jobs.length === 0 ? (
        <EmptyState
          size="sm"
          title="No runs on this shelf yet."
          description="Use “Add to shelf” on a run in Active runs or on its own page."
          action={
            <Button size="sm" variant="secondary" onClick={() => navigate('/jobs')}>
              Go to active runs
            </Button>
          }
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
          {shelf.jobs.map((job) => (
            <RunRow
              key={job.id}
              job={job}
              onRemove={
                canWrite
                  ? () => remove.mutate({ shelfId: shelf.id, jobId: job.id })
                  : undefined
              }
              removeBusy={remove.isPending && remove.variables?.jobId === job.id}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function RunRow({
  job,
  onRemove,
  removeBusy,
}: {
  job: Job;
  onRemove?: () => void;
  removeBusy: boolean;
}) {
  const c = useColors();
  return (
    <Card style={{ padding: `${space['3']} ${space['4']}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
        <Link
          to={`/jobs/${job.id}`}
          style={{
            flex: '1 1 260px',
            minWidth: 0,
            fontFamily: fonts.display,
            fontSize: fontSize.base,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            textDecoration: 'none',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={jobDisplayTitle(job)}
        >
          {jobDisplayTitle(job)}
        </Link>
        <StatusPill status={job.status} size="sm" />
        <span
          style={{
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            color: c.textMuted,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
          }}
        >
          {jobTypeLabel(job.job_type)}
        </span>
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
          {job.video_count} sources · {formatDate(job.created_at)}
        </span>
        {onRemove && (
          <Button size="sm" variant="tertiary" onClick={onRemove} disabled={removeBusy}>
            {removeBusy ? 'Removing…' : 'Remove'}
          </Button>
        )}
      </div>
    </Card>
  );
}

function ShelfDocuments({ shelfId }: { shelfId: string }) {
  const fetchDocs = useShelfDocumentsFetcher(shelfId);
  return (
    <DocumentsBrowser
      queryKey={shelvesKeys.documents(shelfId)}
      fetch={fetchDocs}
      heading="Sources"
      emptyTitle="No sources on this shelf yet."
      emptyDescription="The sources of every run on this shelf gather here, once each, as the runs finish fetching them."
    />
  );
}
