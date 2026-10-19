import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { EchoDataCard } from '../components/echo/EchoDataCard';
import {
  useDeleteContext,
  useEchoConnectors,
  useEchoContext,
  useEchoStatus,
  useRecordContext,
  useRevokeSource,
} from '../hooks/useEcho';
import { useTierCapabilities } from '../hooks/useTierCapabilities';
import { useJobStore } from '../stores/jobStore';
import type { PersonalContextItem } from '../services/echoApi';
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
  Textarea,
} from '../components/primitives';
import { ProgressBar } from '../components/common/ProgressBar';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../theme';
import { formatDate } from '../utils/formatters';
import {
  ECHO_KINDS,
  computeReadiness,
  countBySource,
  dateInputToExpiresAt,
  expiresAtToDateInput,
  formatConfidence,
  groupContextByKind,
  isExpired,
  kindLabel,
  kindMetaFor,
  validateContextKey,
  type KindGroup,
} from '../utils/echoReadiness';
import { detailFromErrorBody, type HttpErrorLike } from '../utils/ingestResults';

function isForbidden(err: unknown): boolean {
  return (err as HttpErrorLike | null)?.response?.status === 403;
}

interface FormState {
  mode: 'create' | 'edit';
  kind: string;
  key: string;
  value: string;
  confidence: number;
  expiresDate: string;
}

/**
 * Echo — Studio-tier personal-context manager.
 *
 * Backend: `backend/app/routers/echo.py` (I-3 foundation, PR #172). The
 * page is honest about what exists: the context store and readiness
 * gates are real; connectors (E-3.2) and the speak-as-me agent (E-3.4)
 * are not, and nothing here pretends otherwise.
 */
export function EchoPage() {
  const c = useColors();
  const navigate = useNavigate();
  const pushToast = useJobStore((s) => s.pushToast);
  const { has, tier, isLoading: tierLoading } = useTierCapabilities();
  const allowed = has('echo_personal_brain');

  const [kindFilter, setKindFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [showExpired, setShowExpired] = useState(false);
  const [form, setForm] = useState<FormState | null>(null);
  const [deleting, setDeleting] = useState<PersonalContextItem | null>(null);
  const [revoking, setRevoking] = useState<{ source: string; count: number } | null>(null);

  const status = useEchoStatus(allowed);
  const connectors = useEchoConnectors(allowed);
  const context = useEchoContext({ include_expired: showExpired }, allowed);
  const record = useRecordContext();
  const del = useDeleteContext();
  const revoke = useRevokeSource();

  const forbidden = isForbidden(status.error) || isForbidden(context.error);
  const allRows = useMemo(() => context.data ?? [], [context.data]);
  const sources = useMemo(() => countBySource(allRows), [allRows]);

  const filteredRows = useMemo(
    () =>
      allRows.filter(
        (r) => (!kindFilter || r.kind === kindFilter) && (!sourceFilter || r.source === sourceFilter),
      ),
    [allRows, kindFilter, sourceFilter],
  );
  const groups = useMemo(() => {
    const all = groupContextByKind(filteredRows);
    return kindFilter ? all.filter((g) => g.meta.kind === kindFilter) : all;
  }, [filteredRows, kindFilter]);

  const readiness = useMemo(
    () => (status.data ? computeReadiness(status.data, connectors.data?.connectors.length ?? 0) : null),
    [status.data, connectors.data],
  );

  const openCreate = (kind = 'interest') =>
    setForm({ mode: 'create', kind, key: '', value: '', confidence: 1, expiresDate: '' });
  const openEdit = (row: PersonalContextItem) =>
    setForm({
      mode: 'edit',
      kind: row.kind,
      key: row.key,
      value: row.value,
      confidence: row.confidence,
      expiresDate: expiresAtToDateInput(row.expires_at),
    });

  const submitForm = (state: FormState) => {
    record.mutate(
      {
        kind: state.kind,
        key: state.key.trim(),
        value: state.value.trim(),
        confidence: state.confidence,
        expires_at: dateInputToExpiresAt(state.expiresDate),
      },
      {
        onSuccess: () => {
          pushToast('success', state.mode === 'edit' ? 'Entry updated.' : 'Echo learned something new.');
          setForm(null);
        },
        onError: (err) =>
          pushToast(
            'error',
            detailFromErrorBody((err as HttpErrorLike).response?.data) ?? 'Could not save this entry.',
          ),
      },
    );
  };

  const confirmDelete = () => {
    if (!deleting) return;
    del.mutate(
      { kind: deleting.kind, key: deleting.key },
      {
        onSuccess: () => {
          pushToast('success', `Forgot “${deleting.key}”.`);
          setDeleting(null);
        },
        onError: () => pushToast('error', 'Delete failed. The entry may already be gone.'),
      },
    );
  };

  const confirmRevoke = () => {
    if (!revoking) return;
    revoke.mutate(revoking.source, {
      onSuccess: (resp) => {
        pushToast('success', `Removed ${resp.deleted_count} ${resp.deleted_count === 1 ? 'entry' : 'entries'} from ${revoking.source}.`);
        setRevoking(null);
      },
      onError: () => pushToast('error', 'Revoke failed.'),
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
          Echo
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
          What the library knows about its reader.{' '}
          <Link to="/echo/inbox" style={{ color: c.accent, fontStyle: 'normal' }}>Open the shares inbox →</Link>
        </p>
      </header>

      {!tierLoading && (!allowed || forbidden) ? (
        <EmptyState
          title="Echo opens at Studio."
          description={`A private store of who you are, so the library can one day answer in your voice. Your plan is ${tier}.`}
          action={<Button onClick={() => navigate('/account/subscription?upgrade=studio')}>See plans</Button>}
        />
      ) : (
        <>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
              gap: space['4'],
              marginBottom: space['6'],
            }}
          >
            <Card>
              <SectionHeading>Readiness</SectionHeading>
              {status.isLoading || !readiness ? (
                status.isError ? (
                  <ErrorLine onRetry={() => status.refetch()}>Couldn't read Echo's status.</ErrorLine>
                ) : (
                  <Skeleton variant="paragraph" />
                )
              ) : (
                <ReadinessView readiness={readiness} />
              )}
            </Card>

            <Card>
              <SectionHeading>Connectors</SectionHeading>
              {connectors.isLoading ? (
                <Skeleton variant="paragraph" />
              ) : connectors.isError ? (
                <ErrorLine onRetry={() => connectors.refetch()}>Couldn't list connectors.</ErrorLine>
              ) : connectors.data && connectors.data.connectors.length > 0 ? (
                <ul style={{ margin: 0, paddingLeft: space['5'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textPrimary }}>
                  {connectors.data.connectors.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  size="sm"
                  title="No connectors yet."
                  description="YouTube watch history, Spotify, email and calendar are planned (E-3.2). Until they ship, everything Echo knows is what you write here."
                />
              )}

              <div style={{ marginTop: space['4'] }}>
                <h3 style={{ margin: `0 0 ${space['2']}`, fontFamily: fonts.ui, fontSize: fontSize.xs, fontWeight: fontWeight.semibold, letterSpacing: '0.08em', textTransform: 'uppercase', color: c.textMuted }}>
                  Sources on record
                </h3>
                {sources.length === 0 ? (
                  <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textMuted, fontStyle: 'italic' }}>
                    Nothing recorded yet.
                  </p>
                ) : (
                  <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
                    {sources.map((s) => (
                      <li key={s.source} style={{ display: 'flex', alignItems: 'center', gap: space['3'] }}>
                        <Badge tone="accent" size="sm">
                          {s.source}
                        </Badge>
                        <span style={{ flex: 1, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
                          {s.count} {s.count === 1 ? 'entry' : 'entries'}
                        </span>
                        <Button size="sm" variant="tertiary" style={{ color: c.error }} onClick={() => setRevoking(s)}>
                          Revoke
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Card>
          </div>

          <section>
            <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap', marginBottom: space['3'] }}>
              <SectionHeading style={{ marginBottom: 0, flex: '1 0 auto', whiteSpace: 'nowrap' }}>
                What Echo knows
                {context.data && (
                  <span style={{ color: c.textMuted, fontWeight: fontWeight.regular }}> ({filteredRows.length})</span>
                )}
              </SectionHeading>
              <div style={{ width: 180 }}>
                <Select value={kindFilter} onChange={(e) => setKindFilter(e.target.value)} aria-label="Filter by kind">
                  <option value="">All kinds</option>
                  {ECHO_KINDS.map((k) => (
                    <option key={k.kind} value={k.kind}>
                      {k.label}
                    </option>
                  ))}
                </Select>
              </div>
              <div style={{ width: 160 }}>
                <Select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)} aria-label="Filter by source">
                  <option value="">All sources</option>
                  {sources.map((s) => (
                    <option key={s.source} value={s.source}>
                      {s.source}
                    </option>
                  ))}
                </Select>
              </div>
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: space['2'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, cursor: 'pointer' }}>
                <input type="checkbox" checked={showExpired} onChange={(e) => setShowExpired(e.target.checked)} style={{ accentColor: c.accent }} />
                Show expired
              </label>
              <Button onClick={() => openCreate(kindFilter || 'interest')}>Add a fact</Button>
            </div>

            {context.isLoading ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
                <Skeleton variant="row" />
                <Skeleton variant="row" />
                <Skeleton variant="row" />
              </div>
            ) : context.isError ? (
              <EmptyState
                size="sm"
                title="Couldn't load what Echo knows."
                description="Something blocked the fetch. Try again."
                action={
                  <Button variant="secondary" size="sm" onClick={() => context.refetch()}>
                    Retry
                  </Button>
                }
              />
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
                {groups.map((g) => (
                  <KindSection
                    key={g.meta.kind}
                    group={g}
                    onAdd={() => openCreate(g.meta.kind)}
                    onEdit={openEdit}
                    onDelete={setDeleting}
                  />
                ))}
              </div>
            )}
          </section>

          <div style={{ marginTop: space['6'] }}>
            <EchoDataCard />
          </div>

          <Card sunken style={{ marginTop: space['6'] }}>
            <h3 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.md, color: c.textPrimary }}>
              Not here yet
            </h3>
            <ul style={{ margin: `${space['2']} 0 0`, paddingLeft: space['5'], fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal }}>
              <li>Pull-mode connectors: YouTube watch history, Spotify, email, calendar (E-3.2)</li>
              <li>Voice and style capture from your own writing (E-3.3)</li>
              <li>The "speak as me" agent that drafts in your voice once readiness is met (E-3.4)</li>
            </ul>
          </Card>
        </>
      )}

      {form && (
        <ContextFormModal
          state={form}
          existingKeys={allRows}
          pending={record.isPending}
          onClose={() => setForm(null)}
          onSubmit={submitForm}
        />
      )}

      <Modal
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title="Forget this entry?"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleting(null)}>
              Keep it
            </Button>
            <Button variant="danger" loading={del.isPending} onClick={confirmDelete}>
              Forget
            </Button>
          </>
        }
      >
        <p style={{ margin: 0, fontFamily: fonts.body, lineHeight: lineHeight.normal }}>
          “{deleting?.key}” under {deleting ? kindLabel(deleting.kind) : ''} will be deleted.
        </p>
      </Modal>

      <Modal
        open={revoking !== null}
        onClose={() => setRevoking(null)}
        title={`Revoke ${revoking?.source ?? ''}?`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRevoking(null)}>
              Cancel
            </Button>
            <Button variant="danger" loading={revoke.isPending} onClick={confirmRevoke}>
              Revoke and delete
            </Button>
          </>
        }
      >
        <p style={{ margin: 0, fontFamily: fonts.body, lineHeight: lineHeight.normal }}>
          Every entry attributed to <strong>{revoking?.source}</strong> ({revoking?.count}) will be
          deleted. This is the opt-out path for a connector; for manual entries it clears
          everything you typed under that source.
        </p>
      </Modal>
    </div>
  );
}

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

function ErrorLine({ children, onRetry }: { children: React.ReactNode; onRetry: () => void }) {
  const c = useColors();
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error }}>
      <span>{children}</span>
      <Button size="sm" variant="tertiary" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}

function ReadinessView({ readiness }: { readiness: ReturnType<typeof computeReadiness> }) {
  const c = useColors();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: space['3'] }}>
        <span style={{ fontFamily: fonts.display, fontSize: fontSize['3xl'], fontWeight: fontWeight.semibold, color: readiness.ready ? c.forest : c.accent, lineHeight: 1 }}>
          {readiness.percent}%
        </span>
        <span style={{ fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary }}>
          {readiness.ready ? 'Echo has enough to learn from.' : "You're on the way. Three gates, all required."}
        </span>
      </div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        {readiness.parts.map((p) => (
          <li key={p.gate} style={{ display: 'flex', flexDirection: 'column', gap: space['1'] }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: space['2'] }}>
              <span style={{ flex: 1, fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.textPrimary }}>
                {p.label}
              </span>
              <span style={{ fontFamily: fonts.mono, fontSize: fontSize.xs, color: p.met ? c.success : c.textSecondary }}>
                {p.gate === 'personality' ? (p.met ? 'recorded' : 'missing') : `${p.current} / ${p.target}`}
              </span>
            </div>
            <ProgressBar value={p.fraction * 100} tone={p.met ? 'success' : 'accent'} />
            <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, lineHeight: lineHeight.snug }}>{p.hint}</span>
          </li>
        ))}
      </ul>
      {readiness.voice && (
        <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.snug }}>
          Your voice so far: {readiness.voice.notes} {readiness.voice.notes === 1 ? 'note' : 'notes'} ·{' '}
          {readiness.voice.words.toLocaleString()} words. Notes feed Echo's voice capture; they are not a gate yet.
        </p>
      )}
      {readiness.shares !== null && (
        <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.snug }}>
          Shared with Echo: {readiness.shares} {readiness.shares === 1 ? 'item' : 'items'} in the{' '}
          <Link to="/echo/inbox" style={{ color: c.accent }}>shares inbox</Link>. Not a gate yet.
        </p>
      )}
      <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, fontStyle: 'italic', color: c.textMuted, lineHeight: lineHeight.normal }}>
        {readiness.ready
          ? 'The "speak as me" agent (E-3.4) has not shipped, so nothing acts on this yet.'
          : 'Echo stays quiet until all three gates are met, and nothing speaks for you before then.'}
      </p>
    </div>
  );
}

function KindSection({
  group,
  onAdd,
  onEdit,
  onDelete,
}: {
  group: KindGroup;
  onAdd: () => void;
  onEdit: (row: PersonalContextItem) => void;
  onDelete: (row: PersonalContextItem) => void;
}) {
  const c = useColors();
  return (
    <Card flush>
      <div style={{ padding: `${space['3']} ${space['4']}`, display: 'flex', alignItems: 'baseline', gap: space['3'], borderBottom: group.rows.length ? `1px solid ${c.border}` : 'none' }}>
        <h3 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
          {group.meta.label}
        </h3>
        <Badge tone={group.rows.length ? 'accent' : 'neutral'} size="sm">
          {group.rows.length}
        </Badge>
        <span style={{ flex: 1, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>{group.meta.hint}</span>
        <Button size="sm" variant="tertiary" onClick={onAdd}>
          Add
        </Button>
      </div>
      {group.rows.length === 0 ? (
        <div style={{ padding: `${space['2']} ${space['4']} ${space['3']}`, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textMuted, fontStyle: 'italic' }}>
          Nothing here yet.
        </div>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {group.rows.map((row, i) => (
            <ContextRow key={row.id} row={row} last={i === group.rows.length - 1} onEdit={() => onEdit(row)} onDelete={() => onDelete(row)} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function ContextRow({ row, last, onEdit, onDelete }: { row: PersonalContextItem; last: boolean; onEdit: () => void; onDelete: () => void }) {
  const c = useColors();
  const expired = isExpired(row);
  return (
    <li style={{ padding: `${space['3']} ${space['4']}`, borderBottom: last ? 'none' : `1px solid ${c.border}`, display: 'flex', flexDirection: 'column', gap: space['1'], opacity: expired ? 0.7 : 1 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: space['3'] }}>
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.textPrimary, flex: 1, minWidth: 0 }}>
          {row.key}
        </span>
        <Button size="sm" variant="tertiary" onClick={onEdit}>
          Edit
        </Button>
        <Button size="sm" variant="tertiary" style={{ color: c.error }} onClick={onDelete}>
          Forget
        </Button>
      </div>
      <div style={{ fontFamily: fonts.body, fontSize: fontSize.base, color: c.textPrimary, lineHeight: lineHeight.normal, whiteSpace: 'pre-wrap' }}>
        {row.value}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap', fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
        <Badge tone="neutral" size="sm">
          {row.source}
        </Badge>
        <span>confidence {formatConfidence(row.confidence)}</span>
        <span aria-hidden>·</span>
        <span>captured {formatDate(row.captured_at)}</span>
        {row.expires_at && (
          <>
            <span aria-hidden>·</span>
            {expired ? (
              <Badge tone="warn" size="sm">
                Expired {formatDate(row.expires_at)}
              </Badge>
            ) : (
              <span>expires {formatDate(row.expires_at)}</span>
            )}
          </>
        )}
      </div>
    </li>
  );
}

function ContextFormModal({
  state: initial,
  existingKeys,
  pending,
  onClose,
  onSubmit,
}: {
  state: FormState;
  existingKeys: PersonalContextItem[];
  pending: boolean;
  onClose: () => void;
  onSubmit: (state: FormState) => void;
}) {
  const c = useColors();
  const [state, setState] = useState<FormState>(initial);
  const meta = kindMetaFor(state.kind);
  const keyError = validateContextKey(state.key);
  const valueError = state.value.trim() ? null : 'Write the fact itself, in your own words.';
  const overwrites =
    state.mode === 'create' &&
    !keyError &&
    existingKeys.some((r) => r.kind === state.kind && r.key === state.key.trim());
  const canSubmit = !keyError && !valueError && !pending;

  return (
    <Modal
      open
      onClose={onClose}
      title={state.mode === 'edit' ? 'Edit entry' : 'Add a fact'}
      maxWidth={600}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => canSubmit && onSubmit(state)} disabled={!canSubmit} loading={pending}>
            {state.mode === 'edit' ? 'Save' : overwrites ? 'Overwrite' : 'Add'}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) onSubmit(state);
        }}
        style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: space['3'] }}>
          <FormField label="Kind" helperText={meta.hint}>
            {(id) => (
              <Select id={id} value={state.kind} disabled={state.mode === 'edit'} onChange={(e) => setState({ ...state, kind: e.target.value })}>
                {ECHO_KINDS.map((k) => (
                  <option key={k.kind} value={k.kind}>
                    {k.label}
                  </option>
                ))}
              </Select>
            )}
          </FormField>
          <FormField
            label="Label"
            required
            errorText={state.key && keyError ? keyError : undefined}
            helperText={
              state.mode === 'edit'
                ? 'Labels cannot be renamed; forget the entry and add it again.'
                : overwrites
                  ? `An entry with this label already exists under ${meta.label}; adding will overwrite it.`
                  : 'A short handle for this fact.'
            }
          >
            {(id) => (
              <Input
                id={id}
                value={state.key}
                disabled={state.mode === 'edit'}
                maxLength={128}
                placeholder={meta.exampleKey ? `e.g. ${meta.exampleKey}` : ''}
                onChange={(e) => setState({ ...state, key: e.target.value })}
                autoFocus={state.mode === 'create'}
              />
            )}
          </FormField>
        </div>

        <FormField label="The fact" required errorText={state.value && valueError ? valueError : undefined}>
          {(id) => (
            <Textarea
              id={id}
              rows={4}
              value={state.value}
              onChange={(e) => setState({ ...state, value: e.target.value })}
              placeholder="In your own words. Echo keeps it verbatim."
              style={{ fontFamily: fonts.body }}
              autoFocus={state.mode === 'edit'}
            />
          )}
        </FormField>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: space['3'] }}>
          <FormField label="Confidence" helperText="How sure you are, 0 to 1.">
            {(id) => (
              <Input
                id={id}
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={state.confidence}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  setState({ ...state, confidence: Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : 1 });
                }}
              />
            )}
          </FormField>
          <FormField label="Expires" optional helperText="Leave empty for facts that stay true.">
            {(id) => <Input id={id} type="date" value={state.expiresDate} onChange={(e) => setState({ ...state, expiresDate: e.target.value })} />}
          </FormField>
        </div>

        <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, lineHeight: lineHeight.snug, borderTop: `1px solid ${c.border}`, paddingTop: space['3'], borderRadius: radius.none }}>
          Saved with source <strong>manual</strong>. Only you can read this; nothing acts on it until the speak-as-me agent ships.
        </p>
      </form>
    </Modal>
  );
}
