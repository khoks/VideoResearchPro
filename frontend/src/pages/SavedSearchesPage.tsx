import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useColors } from '../hooks/useTheme';
import { useTierCapabilities } from '../hooks/useTierCapabilities';
import {
  useDeleteSavedSearch,
  useRunSavedSearchNow,
  useSavedSearchRuns,
  useSavedSearches,
  useUpdateSavedSearch,
} from '../hooks/useSavedSearches';
import { AnswerCutOffNote } from '../components/qa/AnswerCutOffNote';
import { ScheduleFields } from '../components/savedSearches/ScheduleFields';
import { Badge, Button, Card, EmptyState, Skeleton, type BadgeTone } from '../components/primitives';
import { inlineErrorMessage } from '../utils/apiError';
import { describeCadence, parseUtc } from '../utils/cadence';
import type { Cadence, SavedSearch, SavedSearchRun, SavedSearchStatus } from '../services/savedSearchesApi';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../theme';

const STATUS: Record<SavedSearchStatus, { label: string; tone: BadgeTone }> = {
  ok: { label: 'Answered', tone: 'success' },
  no_new_sources: { label: 'Nothing new to read', tone: 'neutral' },
  failed: { label: 'Last run failed', tone: 'error' },
  quota_exceeded: { label: 'Skipped: monthly quota', tone: 'warn' },
  feature_unavailable: { label: 'Not in your plan', tone: 'warn' },
  scope_missing: { label: 'Shelf deleted', tone: 'warn' },
};

function when(iso: string | null): string {
  if (!iso) return '—';
  return parseUtc(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/**
 * `/saved-searches` (S-8.3.2): every pinned library question, its schedule,
 * when it runs next and what the last run said. Run now, pause, edit the
 * schedule, delete. Pro and Studio (`saved_searches`).
 */
export function SavedSearchesPage() {
  const c = useColors();
  const navigate = useNavigate();
  const { has, isLoading: tierLoading } = useTierCapabilities();
  const list = useSavedSearches();
  // A failed load is said here alone: the hook sets `meta` (T-3.4.1.26).
  const loadError = list.isError ? inlineErrorMessage(list.error, 'Something blocked the request.') : null;
  // A notification lands here as ?search=<id>&run=<id> (S-8.3.3).
  const [params] = useSearchParams();
  const focusSearch = params.get('search');
  const focusRun = params.get('run');

  const header = (
    <header style={{ marginBottom: space['5'] }}>
      <h1 style={{ fontFamily: fonts.display, fontSize: fontSize['2xl'], fontWeight: fontWeight.semibold, color: c.textPrimary, margin: 0, lineHeight: lineHeight.tight }}>
        Saved searches
      </h1>
      <p style={{ fontFamily: fonts.body, fontStyle: 'italic', fontSize: fontSize.sm, color: c.textMuted, margin: `${space['2']} 0 0`, maxWidth: measure.reading }}>
        Questions you asked once and want asked again, as your library grows.
      </p>
    </header>
  );

  // The tier arrives with /auth/me; until then do not claim the plan lacks it.
  if (tierLoading) {
    return (
      <div aria-busy style={{ maxWidth: measure.grid, margin: '0 auto' }}>
        {header}
        <Skeleton variant="card" height={140} />
      </div>
    );
  }

  if (!has('saved_searches')) {
    return (
      <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
        {header}
        <EmptyState
          title="Saved searches come with Pro."
          description="Pin a library question and it is re-asked on a schedule, so you learn when the answer moves."
          action={<Button onClick={() => navigate('/account/subscription')}>See plans</Button>}
        />
      </div>
    );
  }

  const items = list.data?.items ?? [];
  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
      {header}
      {list.data && list.data.cap !== -1 && (
        <p style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted, margin: `0 0 ${space['3']}` }}>
          {list.data.active} of {list.data.cap} active
        </p>
      )}
      {list.isLoading ? (
        <div aria-busy style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          <Skeleton variant="card" height={140} />
          <Skeleton variant="card" height={140} />
        </div>
      ) : list.isError ? (
        loadError && (
          <EmptyState
            size="sm"
            title="Couldn't load your saved searches."
            description={loadError}
            action={
              <Button variant="secondary" onClick={() => void list.refetch()}>
                Retry
              </Button>
            }
          />
        )
      ) : items.length === 0 ? (
        <EmptyState
          title="Nothing pinned yet."
          description="Ask the library a question, then choose Pin this question on its answer to have it re-asked daily, weekly or monthly."
          action={<Button onClick={() => navigate('/library/qa')}>Ask the library</Button>}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
          {items.map((s) => (
            <SavedSearchCard key={s.id} search={s} focusRun={focusSearch === s.id ? focusRun : null} />
          ))}
        </div>
      )}
    </div>
  );
}

function SavedSearchCard({ search: s, focusRun }: { search: SavedSearch; focusRun: string | null }) {
  const c = useColors();
  const [historyOpen, setHistoryOpen] = useState(!!focusRun);
  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (focusRun) cardRef.current?.scrollIntoView?.({ block: 'start' });
  }, [focusRun]);
  const update = useUpdateSavedSearch();
  const remove = useDeleteSavedSearch();
  const runNow = useRunSavedSearchNow();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Cadence | null>(s.cadence);
  const [queued, setQueued] = useState(false);
  const status = s.last_status ? STATUS[s.last_status] : null;
  // Each action says its own failure on its own line, and only there: the hooks
  // set `meta`, so the global toast stands aside, and a 401 says nothing
  // (T-3.4.1.24). One line for all three let one failure hide another.
  const failures = [
    update.isError ? inlineErrorMessage(update.error, 'Could not save the change. Try again.') : null,
    runNow.isError ? inlineErrorMessage(runNow.error, 'Could not start a run. Try again.') : null,
    remove.isError ? inlineErrorMessage(remove.error, 'Could not delete the saved search. Try again.') : null,
  ].filter((line): line is string => !!line);
  // A line follows its mutation's last press, so while a change is out the
  // other changes wait, or the first one's failure would be said nowhere. A
  // delete takes the card and its lines with it, so it waits for any request
  // on the card, and everything waits for a delete (D-159 points 2 and 3).
  const deleting = remove.isPending;
  const changing = update.isPending || deleting;
  const busy = update.isPending || runNow.isPending || deleting;

  const meta = { fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, margin: 0 } as const;

  return (
    <Card ref={cardRef}>
      <article aria-labelledby={`ss-${s.id}`}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: space['3'], flexWrap: 'wrap', alignItems: 'baseline' }}>
          <h2 id={`ss-${s.id}`} style={{ fontFamily: fonts.display, fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.textPrimary, margin: 0, flex: '1 1 320px', lineHeight: lineHeight.snug }}>
            {s.question}
          </h2>
          <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap' }}>
            {!s.enabled && <Badge tone="neutral">Paused</Badge>}
            {status && <Badge tone={status.tone}>{status.label}</Badge>}
            {s.scope && <Badge tone="info">One shelf</Badge>}
          </div>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: `${space['1']} ${space['5']}`, marginTop: space['2'] }}>
          <p style={meta}>{describeCadence(s.cadence)}</p>
          <p style={meta}>Next run: {s.enabled ? when(s.next_run_at) : 'paused'}</p>
          <p style={meta}>Last run: {s.last_run_at ? when(s.last_run_at) : 'not yet'}</p>
          {s.notify_email && <p style={meta}>Emails you when the answer changes</p>}
        </div>

        {s.last_status && s.last_status !== 'ok' && s.last_error && (
          <p role="status" style={{ ...meta, color: c.warn, marginTop: space['2'] }}>
            {s.last_error}
          </p>
        )}

        {s.last_answer ? (
          <div style={{ marginTop: space['3'] }}>
            <p
              style={{
                fontFamily: fonts.body,
                fontSize: fontSize.base,
                color: c.textPrimary,
                lineHeight: lineHeight.normal,
                margin: 0,
                display: '-webkit-box',
                WebkitLineClamp: 4,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
                maxWidth: measure.reading,
              }}
            >
              {s.last_answer}
            </p>
            {s.last_exchange_id && (
              <>
                {/* A cut answer stands in only while there is no full one, so no link here may promise one. */}
                <AnswerCutOffNote cutOff={s.last_answer_cut_off} exchangeId={s.last_exchange_id} />
                <Link to={`/library/qa?exchange=${s.last_exchange_id}`} style={{ ...meta, color: c.accent, display: 'inline-block', marginTop: space['1'] }}>
                  {s.last_answer_cut_off ? 'Read the answer, with citations' : 'Read the full answer, with citations'}
                </Link>
              </>
            )}
          </div>
        ) : (
          <p style={{ ...meta, marginTop: space['3'], color: c.textMuted }}>
            {queued ? 'Queued. The answer appears here in a minute or so.' : 'No answer yet: it runs at the next scheduled time, or now.'}
          </p>
        )}

        {historyOpen && <RunHistory searchId={s.id} focusRun={focusRun} />}

        {editing && draft && (
          <div style={{ marginTop: space['4'] }}>
            <ScheduleFields value={draft} onChange={setDraft} />
          </div>
        )}

        {failures.map((line, i) => (
          <p key={i} role="alert" style={{ ...meta, color: c.error, marginTop: space['3'] }}>
            {line}
          </p>
        ))}

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['2'], marginTop: space['4'], justifyContent: 'flex-end' }}>
          {editing ? (
            <>
              <Button size="sm" variant="tertiary" onClick={() => { setEditing(false); setDraft(s.cadence); }}>
                Cancel
              </Button>
              <Button
                size="sm"
                loading={update.isPending}
                disabled={deleting}
                onClick={() =>
                  draft &&
                  update.mutate({ id: s.id, body: { cadence: draft } }, { onSuccess: () => setEditing(false) })
                }
              >
                Save schedule
              </Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="tertiary" aria-expanded={historyOpen} onClick={() => setHistoryOpen((o) => !o)}>
                {historyOpen ? 'Hide history' : 'History'}
              </Button>
              <Button size="sm" variant="tertiary" onClick={() => setEditing(true)} disabled={!s.cadence || changing}>
                Change schedule
              </Button>
              <Button
                size="sm"
                variant="tertiary"
                disabled={changing}
                onClick={() => update.mutate({ id: s.id, body: { notify_email: !s.notify_email } })}
              >
                {s.notify_email ? 'Stop emails' : 'Email me'}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                loading={update.isPending && update.variables?.body.enabled !== undefined}
                disabled={changing}
                onClick={() => update.mutate({ id: s.id, body: { enabled: !s.enabled } })}
              >
                {s.enabled ? 'Pause' : 'Resume'}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                loading={runNow.isPending}
                disabled={deleting}
                onClick={() => runNow.mutate(s.id, { onSuccess: () => setQueued(true) })}
              >
                Run now
              </Button>
              <Button
                size="sm"
                variant="danger"
                loading={remove.isPending}
                disabled={busy}
                onClick={() => {
                  if (window.confirm('Delete this saved search? Its past answers stay in your library Q&A.')) remove.mutate(s.id);
                }}
              >
                Delete
              </Button>
            </>
          )}
        </div>
      </article>
    </Card>
  );
}

function changeLabel(r: SavedSearchRun): { text: string; tone: BadgeTone } {
  if (r.status !== 'ok') return { text: STATUS[r.status]?.label ?? r.status, tone: STATUS[r.status]?.tone ?? 'neutral' };
  if (r.decided_by === 'cut_off') return { text: 'Cut off', tone: 'warn' };
  if (r.changed === null) return { text: 'First answer', tone: 'info' };
  return r.changed ? { text: 'Changed', tone: 'accent' } : { text: 'No change', tone: 'neutral' };
}

/**
 * The last runs of one saved search (S-8.3.3): when, why, whether the answer
 * changed and what changed, with links to the new and the previous answer.
 * A run named in the URL (from a notification) is outlined.
 */
function RunHistory({ searchId, focusRun }: { searchId: string; focusRun: string | null }) {
  const c = useColors();
  const runs = useSavedSearchRuns(searchId, true);
  const meta = { fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, margin: 0 } as const;

  if (runs.isLoading) return <Skeleton variant="card" height={80} style={{ marginTop: space['3'] }} />;
  if (runs.isError) {
    // The one place a failed load is said: the hook sets `meta` (T-3.4.1.26).
    const failure = inlineErrorMessage(runs.error, "Couldn't load the history.");
    return failure ? (
      <p role="alert" style={{ ...meta, color: c.error, marginTop: space['3'] }}>
        {failure}
      </p>
    ) : null;
  }
  const items = runs.data ?? [];
  if (items.length === 0) return <p style={{ ...meta, marginTop: space['3'] }}>No runs yet.</p>;

  return (
    <ol aria-label="Run history" style={{ listStyle: 'none', margin: `${space['3']} 0 0`, padding: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
      {items.map((r) => {
        const label = changeLabel(r);
        const focused = r.id === focusRun;
        return (
          <li
            key={r.id}
            aria-current={focused ? 'true' : undefined}
            style={{
              padding: space['3'],
              borderRadius: radius.md,
              border: `1px solid ${focused ? c.accent : c.border}`,
              outline: focused ? `2px solid ${c.accent}` : 'none',
              background: c.surfaceAlt,
            }}
          >
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['2'], alignItems: 'center' }}>
              <Badge tone={label.tone} size="sm">
                {label.text}
              </Badge>
              <span style={meta}>{when(r.ran_at)}</span>
              <span style={{ ...meta, color: c.textMuted }}>{r.trigger === 'manual' ? 'Run now' : 'Scheduled'}</span>
            </div>
            {r.diff_summary && (
              <p style={{ fontFamily: fonts.body, fontSize: fontSize.base, color: c.textPrimary, lineHeight: lineHeight.normal, margin: `${space['2']} 0 0` }}>
                {r.diff_summary}
              </p>
            )}
            {r.error && r.status !== 'ok' && <p style={{ ...meta, marginTop: space['1'] }}>{r.error}</p>}
            {r.decided_by === 'cut_off' && r.exchange_id && (
              <>
                <AnswerCutOffNote cutOff exchangeId={r.exchange_id} />
                <p style={{ ...meta, marginTop: space['2'] }}>It was not compared with an earlier answer, so no alert went out.</p>
              </>
            )}
            {(r.exchange_id || (r.changed && r.previous_exchange_id)) && (
              <p style={{ ...meta, marginTop: space['2'], display: 'flex', gap: space['4'], flexWrap: 'wrap' }}>
                {r.exchange_id && (
                  <Link to={`/library/qa?exchange=${r.exchange_id}`} style={{ color: c.accent }}>
                    This answer
                  </Link>
                )}
                {r.changed && r.previous_exchange_id && (
                  <Link to={`/library/qa?exchange=${r.previous_exchange_id}`} style={{ color: c.accent }}>
                    The previous answer
                  </Link>
                )}
              </p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
