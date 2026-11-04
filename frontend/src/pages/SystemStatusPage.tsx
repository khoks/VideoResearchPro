import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useColors } from '../hooks/useTheme';
import { useMe } from '../hooks/useMe';
import {
  systemApi,
  type HealthLLMResponse,
  type HealthUseCase,
  type LLMHealthStatus,
  type SchedulerStatus,
  type YouTubeQuotaStatus,
} from '../services/systemApi';
import { featureLabel } from '../components/common/SystemStatusBanner';
import { apiErrorMessage } from '../utils/apiError';
import { formatDate } from '../utils/formatters';
import { waitForApi } from '../utils/waitForApi';
import { Badge, Button, Card, Modal, Skeleton, type BadgeTone } from '../components/primitives';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../theme';

/**
 * System status (/account/system): what the API process reports about
 * itself, read from the existing health endpoints.
 *
 * - AI models: `GET /health/llm`, the startup probe per use case (provider,
 *   model, reasoning, reachable, latency, error) plus the measured warnings
 *   for the config the process resolved (S-1.14.7).
 * - Scheduler: `GET /health/scheduler` (S-8.3.1).
 * - YouTube quota: `GET /health/quota`.
 * - Restart services: `POST /admin/restart`, offered only to the install's
 *   operators (`MeResponse.is_operator`); the API refuses everyone else
 *   with 403 regardless (`require_operator`, D-111).
 */

export const SYSTEM_QUERY_KEYS = {
  llm: ['system', 'health-llm'] as const,
  scheduler: ['system', 'health-scheduler'] as const,
  quota: ['system', 'health-quota'] as const,
};

const POLL_MS = 60_000;

export function SystemStatusPage() {
  const c = useColors();
  const me = useMe();
  const llm = useQuery({ queryKey: SYSTEM_QUERY_KEYS.llm, queryFn: systemApi.llm, refetchInterval: POLL_MS });
  const scheduler = useQuery({
    queryKey: SYSTEM_QUERY_KEYS.scheduler,
    queryFn: systemApi.scheduler,
    refetchInterval: POLL_MS,
  });
  const quota = useQuery({ queryKey: SYSTEM_QUERY_KEYS.quota, queryFn: systemApi.quota, refetchInterval: POLL_MS });
  const refreshing = llm.isFetching || scheduler.isFetching || quota.isFetching;

  const refreshAll = () => {
    void llm.refetch();
    void scheduler.refetch();
    void quota.refetch();
  };

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: space['5'] }}>
      <header style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: space['3'] }}>
        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <h1
            style={{
              margin: 0,
              fontFamily: fonts.display,
              fontSize: fontSize['2xl'],
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
            }}
          >
            System status
          </h1>
          <p
            style={{
              margin: `${space['2']} 0 0`,
              fontFamily: fonts.body,
              fontSize: fontSize.md,
              color: c.textSecondary,
              lineHeight: lineHeight.normal,
              maxWidth: '75ch',
            }}
          >
            What the server reports about its model connections, its scheduler and today's
            YouTube quota. Refreshes every minute.
          </p>
        </div>
        <Button variant="secondary" size="sm" loading={refreshing} onClick={refreshAll}>
          Refresh
        </Button>
      </header>

      <LLMSection query={llm} />
      <SchedulerSection query={scheduler} />
      <QuotaSection query={quota} />
      {me.data?.is_operator === true && <RestartSection />}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Shared pieces

interface QueryLike<T> {
  data: T | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => unknown;
}

function Section({
  title,
  badge,
  children,
  id,
}: {
  title: string;
  badge?: ReactNode;
  children: ReactNode;
  id: string;
}) {
  const c = useColors();
  return (
    <Card flush data-system-section={id} aria-labelledby={`system-${id}`} role="region">
      <div
        style={{
          padding: `${space['4']} ${space['5']}`,
          borderBottom: `1px solid ${c.border}`,
          display: 'flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: space['3'],
        }}
      >
        <h2
          id={`system-${id}`}
          style={{
            margin: 0,
            fontFamily: fonts.display,
            fontSize: fontSize.lg,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
          }}
        >
          {title}
        </h2>
        {badge}
      </div>
      <div style={{ padding: `${space['4']} ${space['5']}`, display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        {children}
      </div>
    </Card>
  );
}

function Note({ children }: { children: ReactNode }) {
  const c = useColors();
  return (
    <p
      style={{
        margin: 0,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        color: c.textMuted,
        lineHeight: lineHeight.normal,
        maxWidth: '75ch',
      }}
    >
      {children}
    </p>
  );
}

function LoadState<T>({ query, what, children }: { query: QueryLike<T>; what: string; children: (data: T) => ReactNode }) {
  if (query.isLoading) return <Skeleton variant="card" height={96} />;
  if (query.isError || query.data === undefined) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'], alignItems: 'flex-start' }}>
        <Note>{apiErrorMessage(query.error, `The server did not answer for ${what}.`)}</Note>
        <Button variant="secondary" size="sm" onClick={() => void query.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  return <>{children(query.data)}</>;
}

function Facts({ items }: { items: Array<[string, ReactNode]> }) {
  const c = useColors();
  return (
    <dl
      style={{
        margin: 0,
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
        gap: `${space['3']} ${space['5']}`,
      }}
    >
      {items.map(([term, value]) => (
        <div key={term} style={{ minWidth: 0 }}>
          <dt
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.xs,
              fontWeight: fontWeight.medium,
              color: c.textMuted,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
            }}
          >
            {term}
          </dt>
          <dd
            style={{
              margin: `${space['1']} 0 0`,
              fontFamily: fonts.ui,
              fontSize: fontSize.base,
              color: c.textPrimary,
              overflowWrap: 'anywhere',
            }}
          >
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function formatSeconds(s: number): string {
  if (s % 60 === 0 && s >= 60) return `${s / 60} min`;
  return `${s} s`;
}

// ──────────────────────────────────────────────────────────────
// AI models

const LLM_STATUS: Record<LLMHealthStatus, { label: string; tone: BadgeTone }> = {
  ok: { label: 'All reachable', tone: 'success' },
  degraded: { label: 'Degraded', tone: 'warn' },
  down: { label: 'Down', tone: 'error' },
  unknown: { label: 'Not probed yet', tone: 'neutral' },
};

const WARNING_TITLES: Record<string, string> = {
  unacceptable: 'Measured unacceptable for this function',
  weaker: 'Measured weaker than the default here',
  not_vision_capable: 'Not a known image-capable model',
};

function LLMSection({ query }: { query: QueryLike<HealthLLMResponse> }) {
  const status = query.data?.summary.status;
  return (
    <Section
      id="llm"
      title="AI models"
      badge={
        status ? (
          <Badge tone={LLM_STATUS[status]?.tone ?? 'neutral'} size="sm">
            {LLM_STATUS[status]?.label ?? status}
          </Badge>
        ) : undefined
      }
    >
      <LoadState query={query} what="the model probe">
        {(data) => <LLMBody data={data} />}
      </LoadState>
    </Section>
  );
}

function LLMBody({ data }: { data: HealthLLMResponse }) {
  const c = useColors();
  const [problemsOnly, setProblemsOnly] = useState(false);
  const rows = useMemo(() => Object.entries(data.use_cases), [data.use_cases]);
  const failed = rows.filter(([, r]) => !r.ok).length;
  const warned = rows.filter(([, r]) => (r.warnings ?? []).length > 0).length;
  const shown = problemsOnly ? rows.filter(([, r]) => !r.ok || (r.warnings ?? []).length > 0) : rows;
  const checked = data.summary.last_checked_at;

  return (
    <>
      <Note>
        {checked
          ? `Probed when the API started, ${formatDate(new Date(checked * 1000).toISOString())}. `
          : 'No probe has run in this API process yet. '}
        One short request per provider and model. The Celery worker is not probed; a failure
        there shows on the run's own page.
      </Note>
      {data.summary.unavailable_features.length > 0 && (
        <div
          role="note"
          style={{
            borderLeft: `3px solid ${c.error}`,
            background: c.errorSubtle,
            borderRadius: radius.sm,
            padding: `${space['2']} ${space['3']}`,
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            color: c.textPrimary,
          }}
        >
          <span style={{ fontWeight: fontWeight.semibold }}>Unavailable:</span>{' '}
          {data.summary.unavailable_features.map(featureLabel).join(', ')}.
        </div>
      )}
      {rows.length === 0 ? null : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: space['3'] }}>
            <span data-llm-counts style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
              {rows.length} functions · {failed} failed · {warned} with a warning
            </span>
            <label
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: space['2'],
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                color: c.textSecondary,
                cursor: 'pointer',
              }}
            >
              <input type="checkbox" checked={problemsOnly} onChange={(e) => setProblemsOnly(e.target.checked)} />
              Only failures and warnings
            </label>
          </div>
          {shown.length === 0 ? (
            <Note>Nothing failed and nothing carries a warning.</Note>
          ) : (
            <div style={{ overflowX: 'auto', maxWidth: '100%' }}>
              <table
                data-llm-table
                style={{ width: '100%', borderCollapse: 'collapse', fontFamily: fonts.ui, fontSize: fontSize.sm }}
              >
                <thead>
                  <tr>
                    <Th>Function</Th>
                    <Th>Provider</Th>
                    <Th>Model</Th>
                    <Th>Reasoning</Th>
                    <Th>Result</Th>
                    <Th align="right">Latency</Th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map(([useCase, r]) => (
                    <UseCaseRows key={useCase} useCase={useCase} row={r} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}

function Th({ children, align = 'left' }: { children: ReactNode; align?: 'left' | 'right' }) {
  const c = useColors();
  return (
    <th
      style={{
        textAlign: align,
        padding: `${space['1']} ${space['2']}`,
        borderBottom: `1px solid ${c.borderStrong}`,
        color: c.textMuted,
        fontSize: fontSize.xs,
        fontWeight: fontWeight.semibold,
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </th>
  );
}

function UseCaseRows({ useCase, row }: { useCase: string; row: HealthUseCase }) {
  const c = useColors();
  const warnings = row.warnings ?? [];
  const hasDetail = !!row.error || warnings.length > 0;
  const cell = {
    padding: `${space['2']} ${space['2']}`,
    borderBottom: hasDetail ? 'none' : `1px solid ${c.border}`,
    color: c.textSecondary,
    verticalAlign: 'top' as const,
  };
  return (
    <>
      <tr data-use-case={useCase}>
        <td style={{ ...cell, color: c.textPrimary, fontFamily: fonts.mono, fontSize: fontSize.xs }}>{useCase}</td>
        <td style={cell}>{row.provider}</td>
        <td style={{ ...cell, fontFamily: fonts.mono, fontSize: fontSize.xs, whiteSpace: 'nowrap' }}>{row.model}</td>
        <td style={cell}>{row.reasoning}</td>
        <td style={cell}>
          <Badge tone={row.ok ? 'success' : 'error'} size="sm">
            {row.ok ? 'OK' : 'Failed'}
          </Badge>
        </td>
        <td style={{ ...cell, textAlign: 'right', whiteSpace: 'nowrap' }}>{row.latency_ms} ms</td>
      </tr>
      {hasDetail && (
        <tr data-use-case-detail={useCase}>
          <td
            colSpan={6}
            style={{
              padding: `0 ${space['2']} ${space['2']}`,
              borderBottom: `1px solid ${c.border}`,
              fontSize: fontSize.xs,
              lineHeight: lineHeight.snug,
            }}
          >
            {row.error && (
              <div style={{ color: c.error, overflowWrap: 'anywhere' }}>
                <span style={{ fontWeight: fontWeight.semibold }}>Error:</span> {row.error}
              </div>
            )}
            {warnings.map((w) => (
              <div key={`${w.kind}:${w.model}`} style={{ color: c.textPrimary, marginTop: row.error ? space['1'] : 0 }}>
                <span style={{ fontWeight: fontWeight.semibold, color: w.kind === 'weaker' ? c.warn : c.error }}>
                  {WARNING_TITLES[w.kind] ?? w.kind}
                  {w.decision_id ? ` (${w.decision_id})` : ''}.
                </span>{' '}
                {w.why}
              </div>
            ))}
          </td>
        </tr>
      )}
    </>
  );
}

// ──────────────────────────────────────────────────────────────
// Scheduler

function SchedulerSection({ query }: { query: QueryLike<SchedulerStatus> }) {
  const enabled = query.data?.enabled;
  return (
    <Section
      id="scheduler"
      title="Scheduler"
      badge={
        enabled === undefined ? undefined : (
          <Badge tone={enabled ? 'success' : 'neutral'} size="sm">
            {enabled ? 'On' : 'Off'}
          </Badge>
        )
      }
    >
      <LoadState query={query} what="the scheduler">
        {(s) => (
          <>
            <Facts
              items={[
                ['Tick every', formatSeconds(s.tick_seconds)],
                ['Last dispatch', s.last_run_at ? formatDate(s.last_run_at) : 'Never'],
                ['Scheduled rows', `${s.rows.total} (${s.rows.enabled} enabled)`],
                ['Due now', s.rows.due],
                ['Claimed', s.rows.claimed],
                ['Lease / grace', `${formatSeconds(s.lease_seconds)} / ${formatSeconds(s.grace_seconds)}`],
                ['Kinds', s.kinds.length ? s.kinds.join(', ') : 'None registered'],
              ]}
            />
            <Note>
              The counts come from the database. The kinds are the ones this API process
              registered; the worker, which does the dispatching, can differ. A last dispatch
              that stops moving while rows are due means the beat process is not running.
            </Note>
          </>
        )}
      </LoadState>
    </Section>
  );
}

// ──────────────────────────────────────────────────────────────
// YouTube quota

function QuotaSection({ query }: { query: QueryLike<YouTubeQuotaStatus> }) {
  return (
    <Section id="quota" title="YouTube quota">
      <LoadState query={query} what="the YouTube quota">
        {(q) => <QuotaBody q={q} />}
      </LoadState>
    </Section>
  );
}

function QuotaBody({ q }: { q: YouTubeQuotaStatus }) {
  const c = useColors();
  const share = q.daily_limit > 0 ? Math.min(1, q.used / q.daily_limit) : 0;
  const fill = share >= 1 ? c.error : share >= 0.8 ? c.warn : c.success;
  return (
    <>
      <p data-quota-line style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.base, color: c.textPrimary }}>
        <strong>{q.used.toLocaleString('en-US')}</strong> of {q.daily_limit.toLocaleString('en-US')} units
        used on {q.date} (UTC), {q.remaining.toLocaleString('en-US')} left.
      </p>
      <div
        role="meter"
        aria-label="YouTube quota used today"
        aria-valuemin={0}
        aria-valuemax={q.daily_limit}
        aria-valuenow={q.used}
        style={{ height: 8, background: c.surfaceAlt, borderRadius: radius.pill, overflow: 'hidden' }}
      >
        <div style={{ width: `${share * 100}%`, height: '100%', background: fill }} />
      </div>
      <Note>
        Counted by this install per UTC day. A search call costs 100 units; a call that reads
        videos, channels or a playlist page costs 1.
      </Note>
    </>
  );
}

// ──────────────────────────────────────────────────────────────
// Restart (operators only)

type RestartState =
  | { phase: 'idle' }
  | { phase: 'sending' }
  | { phase: 'waiting'; message: string }
  | { phase: 'back' }
  | { phase: 'timeout' }
  | { phase: 'failed'; message: string };

function RestartSection() {
  const c = useColors();
  const qc = useQueryClient();
  const [keepFrontend, setKeepFrontend] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [state, setState] = useState<RestartState>({ phase: 'idle' });
  const unmounted = useRef(false);
  useEffect(() => {
    unmounted.current = false;
    return () => {
      unmounted.current = true;
    };
  }, []);

  const restart = async () => {
    setConfirming(false);
    setState({ phase: 'sending' });
    try {
      const res = await systemApi.restart(keepFrontend);
      if (unmounted.current) return;
      setState({ phase: 'waiting', message: res.message });
    } catch (err) {
      if (!unmounted.current) {
        setState({ phase: 'failed', message: apiErrorMessage(err, 'The restart was not accepted.') });
      }
      return;
    }
    const result = await waitForApi({ ping: systemApi.ping, isCancelled: () => unmounted.current });
    if (result === 'cancelled') return;
    setState({ phase: result });
    if (result === 'back') void qc.invalidateQueries();
  };

  const busy = state.phase === 'sending' || state.phase === 'waiting';
  return (
    <Section id="restart" title="Restart services" badge={<Badge tone="info" size="sm">Operator</Badge>}>
      <Note>
        Restarts Redis if it is stopped, then the API, the Celery worker, the scheduler beat
        and, unless you keep it, the frontend dev server (scripts/restart_services.ps1).
        Windows hosts only. Work the worker is doing at that moment is interrupted.
      </Note>
      <label
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: space['2'],
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          color: c.textSecondary,
          cursor: 'pointer',
        }}
      >
        <input
          type="checkbox"
          checked={keepFrontend}
          disabled={busy}
          onChange={(e) => setKeepFrontend(e.target.checked)}
        />
        Keep the frontend dev server running
      </label>
      <div>
        <Button variant="danger" size="sm" loading={busy} onClick={() => setConfirming(true)}>
          Restart services
        </Button>
      </div>
      <RestartStatus state={state} />

      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title="Restart every service?"
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => void restart()}>
              Restart now
            </Button>
          </>
        }
      >
        The server goes quiet for about ten seconds while it restarts, for everyone using this
        install.{' '}
        {keepFrontend
          ? 'The frontend dev server keeps running.'
          : 'The frontend dev server restarts too, so this page may reload.'}
      </Modal>
    </Section>
  );
}

function RestartStatus({ state }: { state: RestartState }) {
  const c = useColors();
  let text: string | null = null;
  let color = c.textSecondary;
  switch (state.phase) {
    case 'sending':
      text = 'Asking the server to restart…';
      break;
    case 'waiting':
      text = `${state.message} Waiting for the API to answer again…`;
      break;
    case 'back':
      text = 'The API is answering again.';
      color = c.success;
      break;
    case 'timeout':
      text =
        'The API has not answered for 90 seconds. Check the logs at the repo root (.uvicorn.*.log, .celery.*.log).';
      color = c.error;
      break;
    case 'failed':
      text = state.message;
      color = c.error;
      break;
    default:
      text = null;
  }
  if (!text) return null;
  return (
    <p
      role="status"
      aria-live="polite"
      data-restart-status={state.phase}
      style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color, lineHeight: lineHeight.normal }}
    >
      {text}
    </p>
  );
}
