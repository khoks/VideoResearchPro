import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  useAuthorKinds,
  useAuthorOutputs,
  useCreateOutput,
  useCancelOutput,
  useDeleteOutput,
} from '../hooks/useAuthor';
import { useOutputsProgress } from '../hooks/useOutputProgress';
import { ProgressBar } from '../components/common/ProgressBar';
import { useJobs } from '../hooks/useJobs';
import { useTierCapabilities } from '../hooks/useTierCapabilities';
import { useJobStore } from '../stores/jobStore';
import { authorApi, type OutputItem } from '../services/authorApi';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  FormField,
  Input,
  Modal,
  Select,
  Skeleton,
  Spinner,
} from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../theme';
import { formatDate } from '../utils/formatters';
import { downloadUrl } from '../utils/download';
import {
  describeCreateError,
  isActiveOutput,
  isOrphanedPending,
  kindMeta,
  outputDownloadFilename,
  outputMediaType,
  outputProgressLine,
  outputSizeLabel,
  outputStatusLabel,
  outputStatusTone,
  parseCreateIntent,
  partitionKinds,
} from '../utils/authorOutputs';
import type { HttpErrorLike } from '../utils/ingestResults';
import type { Job } from '../types/job';

const OUTPUT_STATUSES = ['pending', 'generating', 'completed', 'failed'] as const;

function isForbidden(err: unknown): boolean {
  return (err as HttpErrorLike | null)?.response?.status === 403;
}

/**
 * Author Studio — Pro tier and up.
 *
 * Backend: `backend/app/routers/author.py` (I-6 foundation, PR #173).
 * Only `book` has an outputter today; every other kind the schema knows
 * is shown honestly as "coming later" and never offered a create button.
 */
export function AuthorPage() {
  const c = useColors();
  const navigate = useNavigate();
  const pushToast = useJobStore((s) => s.pushToast);
  const { has, tier, isLoading: tierLoading } = useTierCapabilities();
  const allowed = has('author_studio');

  const [kindFilter, setKindFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  // S-6.1.1: `/author?new=book&job=<id>` (the job page's "Add to a book")
  // opens the create flow with that run pre-selected.
  const [searchParams, setSearchParams] = useSearchParams();
  const [intent] = useState(() => parseCreateIntent(searchParams));
  const [creatingKind, setCreatingKind] = useState<string | null>(() => intent?.kind ?? null);
  const [deleting, setDeleting] = useState<OutputItem | null>(null);

  const kinds = useAuthorKinds(allowed);
  const outputs = useAuthorOutputs(
    { kind: kindFilter || undefined, status: statusFilter || undefined },
    allowed,
  );
  const deleteMut = useDeleteOutput();
  const cancelMut = useCancelOutput();
  // S-6.7.1: the output this visit just queued; it opens when it finishes.
  const [awaiting, setAwaiting] = useState<string | null>(null);
  const activeIds = useMemo(
    () => (outputs.data ?? []).filter((o) => isActiveOutput(o.status) && !isOrphanedPending(o)).map((o) => o.id),
    [outputs.data],
  );
  useOutputsProgress(awaiting && !activeIds.includes(awaiting) ? [...activeIds, awaiting] : activeIds);
  useEffect(() => {
    if (!awaiting) return;
    const row = outputs.data?.find((o) => o.id === awaiting);
    if (!row || isActiveOutput(row.status)) return;
    setAwaiting(null);
    if (row.status === 'completed') {
      pushToast('success', `“${row.title}” is ready.`);
      navigate(`/author/outputs/${row.id}`);
    } else if (row.status === 'failed') {
      pushToast('error', row.error_message ?? 'Generation failed.');
    }
  }, [awaiting, outputs.data, navigate, pushToast]);

  const cancel = (output: OutputItem) =>
    cancelMut.mutate(output.id, {
      onSuccess: () => pushToast('info', `Cancelled “${output.title}”.`),
      onError: () => pushToast('error', 'Could not cancel; it may already have finished.'),
    });

  const forbidden = isForbidden(kinds.error) || isForbidden(outputs.error);
  const partition = useMemo(() => partitionKinds(kinds.data), [kinds.data]);

  const download = async (output: OutputItem) => {
    try {
      const text = await authorApi.getContent(output.id);
      const blob = new Blob([text], { type: outputMediaType(output) });
      const url = URL.createObjectURL(blob);
      downloadUrl(url, outputDownloadFilename(output));
      window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
    } catch {
      pushToast('error', 'Could not fetch the manuscript for download.');
    }
  };

  const confirmDelete = () => {
    if (!deleting) return;
    deleteMut.mutate(deleting.id, {
      onSuccess: () => {
        pushToast('success', `Deleted “${deleting.title}”.`);
        setDeleting(null);
      },
      onError: () => pushToast('error', 'Delete failed. The output may already be gone.'),
    });
  };

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
      <header style={{ marginBottom: space['5'] }}>
        <h1
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            margin: 0,
            lineHeight: lineHeight.tight,
          }}
        >
          Author Studio
        </h1>
        <p
          style={{
            fontFamily: fonts.body,
            fontStyle: 'italic',
            fontSize: fontSize.sm,
            color: c.textMuted,
            margin: `${space['2']} 0 0`,
          }}
        >
          What the shelves can become once you stop asking and start writing.
        </p>
      </header>

      {!tierLoading && (!allowed || forbidden) ? (
        <EmptyState
          title="Author Studio opens at Pro."
          description={`Bind finished research runs into a book, with sites, decks, newsletters and reels to follow. Your plan is ${tier}.`}
          action={
            <Button onClick={() => navigate('/account/subscription?upgrade=pro')}>
              See plans
            </Button>
          }
        />
      ) : (
        <>
          <section style={{ marginBottom: space['6'] }}>
            <SectionHeading>What you can make</SectionHeading>
            {kinds.isLoading ? (
              <div style={kindGrid}>
                <Skeleton variant="card" />
                <Skeleton variant="card" />
                <Skeleton variant="card" />
              </div>
            ) : kinds.isError ? (
              <EmptyState
                size="sm"
                title="Couldn't load output kinds."
                description="The studio needs the backend to say what it can generate."
                action={
                  <Button variant="secondary" size="sm" onClick={() => kinds.refetch()}>
                    Retry
                  </Button>
                }
              />
            ) : (
              <div style={kindGrid}>
                {partition.available.map((kind) => (
                  <KindCard key={kind} kind={kind} available onCreate={() => setCreatingKind(kind)} />
                ))}
                {partition.comingLater.map((kind) => (
                  <KindCard key={kind} kind={kind} available={false} />
                ))}
              </div>
            )}
          </section>

          <section>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: space['3'],
                flexWrap: 'wrap',
                marginBottom: space['3'],
              }}
            >
              <SectionHeading style={{ marginBottom: 0, flex: '1 0 auto', whiteSpace: 'nowrap' }}>
                Your outputs
                {outputs.data && (
                  <span style={{ color: c.textMuted, fontWeight: fontWeight.regular }}>
                    {' '}
                    ({outputs.data.length})
                  </span>
                )}
              </SectionHeading>
              <div style={{ width: 170 }}>
                <Select
                  value={kindFilter}
                  onChange={(e) => setKindFilter(e.target.value)}
                  aria-label="Filter by kind"
                >
                  <option value="">All kinds</option>
                  {(kinds.data?.supported ?? ['book']).map((k) => (
                    <option key={k} value={k}>
                      {kindMeta(k).label}
                    </option>
                  ))}
                </Select>
              </div>
              <div style={{ width: 170 }}>
                <Select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  aria-label="Filter by status"
                >
                  <option value="">All statuses</option>
                  {OUTPUT_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {outputStatusLabel(s)}
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            {outputs.isLoading ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
                <Skeleton variant="row" />
                <Skeleton variant="row" />
                <Skeleton variant="row" />
              </div>
            ) : outputs.isError ? (
              <EmptyState
                size="sm"
                title="Couldn't load your outputs."
                description="Something blocked the fetch. Try again."
                action={
                  <Button variant="secondary" size="sm" onClick={() => outputs.refetch()}>
                    Retry
                  </Button>
                }
              />
            ) : !outputs.data || outputs.data.length === 0 ? (
              <EmptyState
                title={kindFilter || statusFilter ? 'Nothing matches these filters.' : 'Nothing authored yet.'}
                description={
                  kindFilter || statusFilter
                    ? 'Loosen the filters to see the rest of your outputs.'
                    : 'Pick a few finished research runs and bind them into a book.'
                }
                action={
                  !kindFilter && !statusFilter && partition.available.includes('book') ? (
                    <Button onClick={() => setCreatingKind('book')}>New book</Button>
                  ) : undefined
                }
              />
            ) : (
              <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
                {outputs.data.map((row) => (
                  <OutputRow
                    key={row.id}
                    output={row}
                    onView={() => navigate(`/author/outputs/${row.id}`)}
                    onDownload={() => download(row)}
                    onDelete={() => setDeleting(row)}
                    onCancel={() => cancel(row)}
                    cancelling={cancelMut.isPending && cancelMut.variables === row.id}
                  />
                ))}
              </ul>
            )}
          </section>
        </>
      )}

      {creatingKind && allowed && (
        <CreateOutputModal
          kind={creatingKind}
          initialSelected={intent?.kind === creatingKind ? intent.jobIds : undefined}
          onClose={() => {
            setCreatingKind(null);
            if (searchParams.has('new')) setSearchParams({}, { replace: true });
          }}
          onCreated={(output) => {
            setCreatingKind(null);
            if (searchParams.has('new')) setSearchParams({}, { replace: true });
            // S-8.8.3: a finished output opens in the reading room; a queued
            // one (S-6.7.1) opens when the worker finishes it.
            if (output.status === 'completed') navigate(`/author/outputs/${output.id}`);
            else if (isActiveOutput(output.status)) setAwaiting(output.id);
          }}
        />
      )}

      <Modal
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title="Delete this output?"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleting(null)}>
              Keep it
            </Button>
            <Button variant="danger" loading={deleteMut.isPending} onClick={confirmDelete}>
              Delete
            </Button>
          </>
        }
      >
        <p style={{ margin: 0, fontFamily: fonts.body, lineHeight: lineHeight.normal }}>
          “{deleting?.title}” will be removed. The research runs it was built from stay on your
          shelves.
        </p>
      </Modal>
    </div>
  );
}

const kindGrid: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
  gap: space['3'],
};

function SectionHeading({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  const c = useColors();
  return (
    <h2
      style={{
        margin: `0 0 ${space['3']}`,
        fontFamily: fonts.display,
        fontSize: fontSize.lg,
        fontWeight: fontWeight.semibold,
        color: c.textPrimary,
        ...style,
      }}
    >
      {children}
    </h2>
  );
}

function KindCard({ kind, available, onCreate }: { kind: string; available: boolean; onCreate?: () => void }) {
  const c = useColors();
  const meta = kindMeta(kind);
  return (
    <Card sunken={!available} style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
      <div
        style={{
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          fontWeight: fontWeight.semibold,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: available ? c.forest : c.textMuted,
        }}
      >
        {available ? 'Available now' : `Coming later · ${meta.epic}`}
      </div>
      <h3
        style={{
          margin: 0,
          fontFamily: fonts.display,
          fontSize: fontSize.lg,
          fontWeight: fontWeight.semibold,
          color: available ? c.textPrimary : c.textSecondary,
        }}
      >
        {meta.label}
      </h3>
      <p
        style={{
          margin: 0,
          flex: 1,
          fontFamily: fonts.body,
          fontSize: fontSize.sm,
          color: c.textSecondary,
          lineHeight: lineHeight.normal,
        }}
      >
        {meta.description}
      </p>
      {available ? (
        <div>
          <Button size="sm" onClick={onCreate}>
            New {meta.label.toLowerCase()}
          </Button>
        </div>
      ) : (
        <div style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, fontStyle: 'italic' }}>
          The schema accepts it; nothing generates it yet.
        </div>
      )}
    </Card>
  );
}

function OutputRow({
  output,
  onView,
  onDownload,
  onDelete,
  onCancel,
  cancelling,
}: {
  output: OutputItem;
  onView: () => void;
  onDownload: () => void;
  onDelete: () => void;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const c = useColors();
  return (
    <li>
      <Card flush>
        <div style={{ padding: `${space['3']} ${space['4']}`, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
            <Badge tone={outputStatusTone(output.status)} size="sm">
              {outputStatusLabel(output.status)}
            </Badge>
            <span
              style={{
                flex: 1,
                minWidth: 160,
                fontFamily: fonts.display,
                fontSize: fontSize.md,
                fontWeight: fontWeight.semibold,
                color: c.textPrimary,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={output.title}
            >
              {output.title}
            </span>
            <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
              {kindMeta(output.kind).label}
            </span>
            <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
              {outputSizeLabel(output)} · {formatDate(output.created_at)}
            </span>
            <span style={{ display: 'inline-flex', gap: space['1'] }}>
              {output.has_content && (
                <>
                  <Button size="sm" variant="tertiary" onClick={onView}>
                    Read
                  </Button>
                  <Button size="sm" variant="tertiary" onClick={onDownload}>
                    Download
                  </Button>
                </>
              )}
              {isActiveOutput(output.status) && !isOrphanedPending(output) && (
                <Button size="sm" variant="tertiary" onClick={onCancel} loading={cancelling}>
                  Cancel
                </Button>
              )}
              <Button size="sm" variant="tertiary" onClick={onDelete} style={{ color: c.error }}>
                Delete
              </Button>
            </span>
          </div>
          {output.status === 'failed' && output.error_message && (
            <div
              style={{
                fontFamily: fonts.ui,
                fontSize: fontSize.xs,
                color: c.error,
                lineHeight: lineHeight.snug,
                whiteSpace: 'pre-wrap',
              }}
            >
              {output.error_message}
            </div>
          )}
          {isActiveOutput(output.status) && !isOrphanedPending(output) && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: space['1'] }} aria-live="polite">
              <ProgressBar value={output.progress_pct ?? 0} tone="info" />
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
                {outputProgressLine(output)}
              </span>
            </div>
          )}
          {isOrphanedPending(output) && !output.has_content && (
            <div style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, fontStyle: 'italic' }}>
              Created but never generated. This happens when the kind had no generator at the
              time; delete it or wait for that generator to ship.
            </div>
          )}
        </div>
      </Card>
    </li>
  );
}

/**
 * Create + generate in one step. For `book`, source IDs are job IDs (one
 * chapter per run), so the picker lists the user's non-subscription runs
 * and only lets finished runs with a report be chosen.
 */
function CreateOutputModal({
  kind,
  initialSelected,
  onClose,
  onCreated,
}: {
  kind: string;
  /** Run ids to start with ticked (the job page's "Add to a book"). */
  initialSelected?: string[];
  onClose: () => void;
  onCreated: (output: OutputItem) => void;
}) {
  const c = useColors();
  const pushToast = useJobStore((s) => s.pushToast);
  const meta = kindMeta(kind);
  const [title, setTitle] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(() => new Set(initialSelected ?? []));
  const [includeQa, setIncludeQa] = useState(true);
  const [includeToc, setIncludeToc] = useState(true);
  const jobs = useJobs({ limit: 200 });
  const create = useCreateOutput();

  const candidates = useMemo(() => {
    const all = (jobs.data ?? []).filter((j) => j.job_type !== 'subscription');
    const q = search.trim().toLowerCase();
    return q ? all.filter((j) => jobLabel(j).toLowerCase().includes(q)) : all;
  }, [jobs.data, search]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const canSubmit = title.trim().length > 0 && selected.size > 0 && !create.isPending;

  const submit = () => {
    if (!canSubmit) return;
    create.mutate(
      {
        kind,
        title: title.trim(),
        source_ids: [...selected],
        parameters: { include_qa: includeQa, include_toc: includeToc },
      },
      {
        onSuccess: (output) => {
          if (output.status === 'completed') {
            pushToast('success', `${meta.label} ready: “${output.title}”.`);
          } else if (output.status === 'failed') {
            pushToast('error', output.error_message ?? `${meta.label} generation failed.`);
          } else {
            pushToast('info', `Generating “${output.title}” in the background; it opens when it is ready.`);
          }
          onCreated(output);
        },
        onError: (err) => pushToast('error', describeCreateError(err as HttpErrorLike, kind)),
      },
    );
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`New ${meta.label.toLowerCase()}`}
      maxWidth={680}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!canSubmit} loading={create.isPending}>
            {create.isPending ? 'Queueing…' : 'Generate'}
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
        <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal }}>
          {meta.description} Generation runs in the background and shows its progress in the
          list below; the manuscript is deterministic (no model involved yet), so what you pick is
          what you get.
        </p>

        <FormField label="Title" required>
          {(id) => (
            <Input
              id={id}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Two years of the AI policy debate"
              maxLength={256}
              autoFocus
            />
          )}
        </FormField>

        <FormField
          label="Chapters"
          required
          helperText={`${selected.size} selected. One chapter per run: its report, and its Q&A if you keep that on.`}
        >
          {(id) => (
            <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
              <Input
                id={id}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter runs by topic…"
              />
              <div
                style={{
                  maxHeight: 260,
                  overflowY: 'auto',
                  border: `1px solid ${c.border}`,
                  borderRadius: radius.md,
                  background: c.surface,
                }}
              >
                {jobs.isLoading ? (
                  <div style={{ padding: space['4'], textAlign: 'center' }}>
                    <Spinner />
                  </div>
                ) : candidates.length === 0 ? (
                  <div style={{ padding: space['4'], fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textMuted, fontStyle: 'italic' }}>
                    {jobs.data && jobs.data.length > 0
                      ? 'No runs match that filter.'
                      : 'No research runs yet. Finish one and come back; subscription syncs have no report to bind.'}
                  </div>
                ) : (
                  candidates.map((job) => <JobPickRow key={job.id} job={job} checked={selected.has(job.id)} onToggle={() => toggle(job.id)} />)
                )}
              </div>
            </div>
          )}
        </FormField>

        <div style={{ display: 'flex', gap: space['5'], flexWrap: 'wrap' }}>
          <CheckboxRow checked={includeQa} onChange={setIncludeQa} label="Include each run's Q&A" />
          <CheckboxRow checked={includeToc} onChange={setIncludeToc} label="Table of contents" />
        </div>
      </div>
    </Modal>
  );
}

function jobLabel(job: Job): string {
  if (job.topic && job.topic.trim()) return job.topic;
  if (job.channel_list && job.channel_list.length > 0) return `Channel run · ${job.channel_list.join(', ')}`;
  return `Run from ${formatDate(job.created_at)}`;
}

function JobPickRow({ job, checked, onToggle }: { job: Job; checked: boolean; onToggle: () => void }) {
  const c = useColors();
  const eligible = job.status === 'completed' && job.has_report;
  const reason = !eligible
    ? job.status !== 'completed'
      ? `Not finished (${job.status.replace(/_/g, ' ')})`
      : 'No report to bind'
    : null;
  return (
    <label
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: space['3'],
        padding: `${space['2']} ${space['3']}`,
        borderBottom: `1px solid ${c.border}`,
        cursor: eligible ? 'pointer' : 'not-allowed',
        opacity: eligible ? 1 : 0.55,
      }}
    >
      <input type="checkbox" checked={checked} disabled={!eligible} onChange={onToggle} style={{ marginTop: 3, accentColor: c.accent }} />
      <span style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.textPrimary }}>
          {jobLabel(job)}
        </span>
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
          {job.job_type} · {job.video_count} {job.video_count === 1 ? 'source' : 'sources'} · {formatDate(job.created_at)}
          {reason && (
            <>
              {' · '}
              <span style={{ color: c.warn }}>{reason}</span>
            </>
          )}
        </span>
      </span>
    </label>
  );
}

function CheckboxRow({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  const c = useColors();
  return (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: space['2'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textPrimary, cursor: 'pointer' }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} style={{ accentColor: c.accent }} />
      {label}
    </label>
  );
}
