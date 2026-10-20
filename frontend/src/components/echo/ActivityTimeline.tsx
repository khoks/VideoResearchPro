/**
 * The activity timeline (S-3.2.1): what Echo has recorded you doing, newest
 * first, a page at a time. The user's own words (commit messages, PR
 * descriptions) show as the event's text; the payload gives the one-line
 * summary.
 */
import { useState } from 'react';
import { Button, EmptyState, Skeleton } from '../primitives';
import { useEchoActivity } from '../../hooks/useEcho';
import { useColors } from '../../hooks/useTheme';
import type { ActivityItem } from '../../services/echoApi';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';
import { humanize } from './ConnectorsPanel';

const CONNECTOR_LABEL: Record<string, string> = {
  internal: 'Pratidhvani',
  github: 'GitHub',
  // S-3.7.5: events from export imports carry the importer's name.
  google_takeout: 'YouTube (Takeout)',
  spotify_export: 'Spotify',
  goodreads_export: 'Goodreads',
  letterboxd_export: 'Letterboxd',
  strava_export: 'Strava',
};

/** A one-line summary from whatever the event carries. */
export function summarize(item: ActivityItem): string {
  const p = item.payload as Record<string, unknown>;
  const pick = (k: string) => (typeof p[k] === 'string' && (p[k] as string).trim() ? (p[k] as string).trim() : null);
  const firstLine = item.text_content?.split('\n').find((l) => l.trim())?.trim() ?? null;
  const subject = pick('title') ?? firstLine ?? pick('name');
  const where = pick('repo');
  return [subject, where && subject !== where ? `in ${where}` : where].filter(Boolean).join(' ') || '';
}

export function ActivityTimeline({ enabled = true }: { enabled?: boolean }) {
  const c = useColors();
  const [pages, setPages] = useState<(string | undefined)[]>([undefined]);
  return (
    <div data-activity-timeline="">
      {pages.map((before, i) => (
        <ActivityPage
          key={before ?? 'first'}
          before={before}
          enabled={enabled}
          last={i === pages.length - 1}
          onMore={(next) => setPages((ps) => [...ps, next])}
        />
      ))}
      <p style={{ margin: `${space['2']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
        Disconnecting a connector or undoing an import removes its events from here.
      </p>
    </div>
  );
}

function ActivityPage({
  before,
  enabled,
  last,
  onMore,
}: {
  before?: string;
  enabled: boolean;
  last: boolean;
  onMore: (next: string) => void;
}) {
  const c = useColors();
  const q = useEchoActivity(enabled, before);
  if (q.isLoading) return <Skeleton variant="paragraph" />;
  if (!q.data) return null;
  if (!before && q.data.items.length === 0) {
    return (
      <EmptyState
        size="sm"
        title="Nothing recorded yet."
        description="Connect a service above, or share something to Echo: what you do shows up here."
      />
    );
  }
  return (
    <>
      <ol style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: space['2'] }}>
        {q.data.items.map((item) => (
          <li key={item.id} style={{ display: 'grid', gridTemplateColumns: 'minmax(7rem, auto) 1fr', gap: space['3'] }}>
            <time
              dateTime={item.occurred_at}
              style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, paddingTop: 2, whiteSpace: 'nowrap' }}
            >
              {new Date(item.occurred_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })}
            </time>
            <div style={{ minWidth: 0 }}>
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
                {humanize(item.event_type)}
              </span>
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
                {' · '}
                {CONNECTOR_LABEL[item.connector] ?? item.connector}
              </span>
              {summarize(item) && (
                <p
                  style={{
                    margin: 0,
                    fontFamily: fonts.body,
                    fontSize: fontSize.sm,
                    lineHeight: lineHeight.snug,
                    color: c.textSecondary,
                    overflowWrap: 'anywhere',
                  }}
                >
                  {summarize(item)}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
      {last && q.data.next_before && (
        <Button size="sm" variant="tertiary" style={{ marginTop: space['2'] }} onClick={() => onMore(q.data!.next_before!)}>
          Show older
        </Button>
      )}
    </>
  );
}
