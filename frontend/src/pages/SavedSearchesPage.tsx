import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useColors } from '../hooks/useTheme';
import { useTierCapabilities } from '../hooks/useTierCapabilities';
import {
  useDeleteSavedSearch,
  useRunSavedSearchNow,
  useSavedSearches,
  useUpdateSavedSearch,
} from '../hooks/useSavedSearches';
import { ScheduleFields } from '../components/savedSearches/ScheduleFields';
import { Badge, Button, Card, EmptyState, Skeleton, type BadgeTone } from '../components/primitives';
import { apiErrorMessage } from '../utils/apiError';
import { describeCadence, parseUtc } from '../utils/cadence';
import type { Cadence, SavedSearch, SavedSearchStatus } from '../services/savedSearchesApi';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../theme';

const STATUS: Record<SavedSearchStatus, { label: string; tone: BadgeTone }> = {
  ok: { label: 'Answered', tone: 'success' },
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
        <EmptyState
          size="sm"
          title="Couldn't load your saved searches."
          description="Something blocked the request."
          action={
            <Button variant="secondary" onClick={() => void list.refetch()}>
              Retry
            </Button>
          }
        />
      ) : items.length === 0 ? (
        <EmptyState
          title="Nothing pinned yet."
          description="Ask the library a question, then choose Pin this question on its answer to have it re-asked daily, weekly or monthly."
          action={<Button onClick={() => navigate('/library/qa')}>Ask the library</Button>}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
          {items.map((s) => (
            <SavedSearchCard key={s.id} search={s} />
          ))}
        </div>
      )}
    </div>
  );
}

function SavedSearchCard({ search: s }: { search: SavedSearch }) {
  const c = useColors();
  const update = useUpdateSavedSearch();
  const remove = useDeleteSavedSearch();
  const runNow = useRunSavedSearchNow();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Cadence | null>(s.cadence);
  const [queued, setQueued] = useState(false);
  const status = s.last_status ? STATUS[s.last_status] : null;
  const error = update.error ?? runNow.error ?? remove.error;

  const meta = { fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, margin: 0 } as const;

  return (
    <Card>
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
              <Link to={`/library/qa?exchange=${s.last_exchange_id}`} style={{ ...meta, color: c.accent, display: 'inline-block', marginTop: space['1'] }}>
                Read the full answer, with citations
              </Link>
            )}
          </div>
        ) : (
          <p style={{ ...meta, marginTop: space['3'], color: c.textMuted }}>
            {queued ? 'Queued. The answer appears here in a minute or so.' : 'No answer yet: it runs at the next scheduled time, or now.'}
          </p>
        )}

        {editing && draft && (
          <div style={{ marginTop: space['4'] }}>
            <ScheduleFields value={draft} onChange={setDraft} />
          </div>
        )}

        {error && (
          <p role="alert" style={{ ...meta, color: c.error, marginTop: space['3'] }}>
            {apiErrorMessage(error, 'That did not go through. Try again.')}
          </p>
        )}

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['2'], marginTop: space['4'], justifyContent: 'flex-end' }}>
          {editing ? (
            <>
              <Button size="sm" variant="tertiary" onClick={() => { setEditing(false); setDraft(s.cadence); }}>
                Cancel
              </Button>
              <Button
                size="sm"
                loading={update.isPending}
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
              <Button size="sm" variant="tertiary" onClick={() => setEditing(true)} disabled={!s.cadence}>
                Change schedule
              </Button>
              <Button
                size="sm"
                variant="tertiary"
                onClick={() => update.mutate({ id: s.id, body: { notify_email: !s.notify_email } })}
              >
                {s.notify_email ? 'Stop emails' : 'Email me'}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                loading={update.isPending && update.variables?.body.enabled !== undefined}
                onClick={() => update.mutate({ id: s.id, body: { enabled: !s.enabled } })}
              >
                {s.enabled ? 'Pause' : 'Resume'}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                loading={runNow.isPending}
                onClick={() => runNow.mutate(s.id, { onSuccess: () => setQueued(true) })}
              >
                Run now
              </Button>
              <Button
                size="sm"
                variant="danger"
                loading={remove.isPending}
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
