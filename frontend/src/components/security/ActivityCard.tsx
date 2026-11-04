import { useState } from 'react';
import { Button, Card, Skeleton } from '../primitives';
import { useAccountActivity } from '../../hooks/useAccountSecurity';
import { useColors } from '../../hooks/useTheme';
import { describeAuditEvent, describeUserAgent, formatWhen, isWarningEvent } from '../../utils/accountSecurity';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';
import { SectionTitle } from './SectionTitle';

/**
 * Recent account activity (T-5.4.4): sign-ins, failed attempts, password
 * resets, sessions and two-step changes from `GET /auth/audit-log?scope=account`,
 * newest first, a page at a time.
 */
export function ActivityCard() {
  const c = useColors();
  const [page, setPage] = useState(0);
  const activity = useAccountActivity(page);
  const items = activity.data?.items ?? [];
  const muted: React.CSSProperties = { fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted };

  return (
    <Card>
      <SectionTitle>Recent activity</SectionTitle>
      <p style={{ margin: `0 0 ${space['4']}`, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal }}>
        Sign-ins and changes to how you sign in, newest first. A failed sign-in you did not make means someone tried your password.
      </p>
      {activity.isLoading ? (
        <Skeleton variant="row" />
      ) : activity.isError ? (
        <p role="alert" style={{ ...muted, color: c.error, margin: 0 }}>
          Could not load your account activity.
        </p>
      ) : items.length === 0 ? (
        <p style={{ ...muted, margin: 0 }}>{page === 0 ? 'Nothing recorded yet.' : 'No older activity.'}</p>
      ) : (
        <ol aria-label="Account activity" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {items.map((e, i) => {
            const warn = isWarningEvent(e.event);
            return (
              <li
                key={e.id}
                data-event={e.event}
                style={{
                  display: 'flex',
                  gap: space['3'],
                  flexWrap: 'wrap',
                  alignItems: 'baseline',
                  padding: `${space['2']} 0`,
                  borderTop: i === 0 ? 'none' : `1px solid ${c.border}`,
                }}
              >
                <span
                  style={{
                    flex: '1 1 240px',
                    fontFamily: fonts.ui,
                    fontSize: fontSize.base,
                    fontWeight: warn ? fontWeight.semibold : fontWeight.regular,
                    color: warn ? c.error : c.textPrimary,
                  }}
                >
                  {describeAuditEvent(e)}
                </span>
                <span style={{ ...muted, overflowWrap: 'anywhere' }}>
                  {[formatWhen(e.created_at), e.ip_address, describeUserAgent(e.user_agent)].filter(Boolean).join(' · ')}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      {(page > 0 || activity.data?.hasOlder) && (
        <div style={{ display: 'flex', gap: space['2'], marginTop: space['4'], alignItems: 'center' }}>
          <Button size="sm" variant="secondary" disabled={page === 0 || activity.isFetching} onClick={() => setPage((p) => Math.max(0, p - 1))}>
            Newer
          </Button>
          <Button size="sm" variant="secondary" disabled={!activity.data?.hasOlder || activity.isFetching} onClick={() => setPage((p) => p + 1)}>
            Older
          </Button>
          <span style={muted}>Page {page + 1}</span>
        </div>
      )}
    </Card>
  );
}
