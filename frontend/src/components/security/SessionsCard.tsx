import { useState } from 'react';
import { Badge, Button, Card, Skeleton } from '../primitives';
import { SESSIONS_KEY, useRefreshSecurity, useSessions } from '../../hooks/useAccountSecurity';
import { accountSecurityApi, isLiveSession, type SessionInfo } from '../../services/accountSecurityApi';
import { useColors } from '../../hooks/useTheme';
import { apiErrorMessage, inlineErrorMessage } from '../../utils/apiError';
import { describeUserAgent, formatWhen, lastActiveLabel } from '../../utils/accountSecurity';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';
import { SectionTitle } from './SectionTitle';

/**
 * "Where you're signed in" (T-5.4.7): the sessions that still work, this
 * one marked, each revocable, plus "sign out everywhere else". Revoked and
 * expired sessions are left out; the activity list records them.
 */
export function SessionsCard() {
  const c = useColors();
  const sessions = useSessions();
  const refresh = useRefreshSecurity();
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);

  // Said here alone: the hook sets `meta` (T-3.4.1.26). Nothing for a 401.
  const loadError = sessions.isError ? inlineErrorMessage(sessions.error, 'Could not load your sessions.') : null;
  const live = (sessions.data ?? []).filter(isLiveSession);
  // This device first, then the most recently used.
  live.sort((a, b) => Number(b.is_current) - Number(a.is_current) || b.last_used_at.localeCompare(a.last_used_at));
  const others = live.filter((s) => !s.is_current);

  const revoke = async (s: SessionInfo) => {
    setNotice(null);
    setBusy(s.jti);
    try {
      await accountSecurityApi.revokeSession(s.jti);
      setNotice({ tone: 'ok', text: `Signed out ${describeUserAgent(s.user_agent) ?? 'that session'}.` });
    } catch (err) {
      setNotice({ tone: 'error', text: apiErrorMessage(err, 'Could not sign that session out. Try again.') });
    } finally {
      setBusy(null);
      void refresh(SESSIONS_KEY);
    }
  };

  const revokeOthers = async () => {
    setNotice(null);
    setBusy('others');
    try {
      await accountSecurityApi.revokeOtherSessions();
      const n = others.length;
      setNotice({ tone: 'ok', text: `Signed out ${n} other ${n === 1 ? 'session' : 'sessions'}. This one stays signed in.` });
    } catch (err) {
      setNotice({ tone: 'error', text: apiErrorMessage(err, 'Could not sign the other sessions out. Try again.') });
    } finally {
      setBusy(null);
      void refresh(SESSIONS_KEY);
    }
  };

  const muted: React.CSSProperties = { fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted };

  return (
    <Card>
      <SectionTitle>Where you're signed in</SectionTitle>
      <p style={{ margin: `0 0 ${space['4']}`, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal }}>
        Every sign-in starts a session that lasts until it expires or you sign it out. Sign out any you do not recognise.
      </p>

      {sessions.isLoading ? (
        <Skeleton variant="row" />
      ) : sessions.isError ? (
        loadError && (
          <p role="alert" style={{ ...muted, color: c.error, margin: 0 }}>
            {loadError}
          </p>
        )
      ) : live.length === 0 ? (
        <p style={{ ...muted, margin: 0 }}>No active sessions.</p>
      ) : (
        <ul aria-label="Active sessions" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column' }}>
          {live.map((s, i) => (
            <li
              key={s.jti}
              data-session={s.jti}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: space['3'],
                flexWrap: 'wrap',
                padding: `${space['3']} 0`,
                borderTop: i === 0 ? 'none' : `1px solid ${c.border}`,
              }}
            >
              <div style={{ flex: '1 1 240px', minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
                  <span
                    title={s.user_agent ?? undefined}
                    style={{ fontFamily: fonts.ui, fontSize: fontSize.base, fontWeight: fontWeight.medium, color: c.textPrimary }}
                  >
                    {describeUserAgent(s.user_agent) ?? 'Unknown device'}
                  </span>
                  {s.is_current && (
                    <Badge tone="success" size="sm">
                      This device
                    </Badge>
                  )}
                </div>
                <div style={{ ...muted, marginTop: 2, overflowWrap: 'anywhere' }}>
                  {[s.ip_address, `Signed in ${formatWhen(s.created_at)}`, lastActiveLabel(s.last_used_at)].filter(Boolean).join(' · ')}
                </div>
              </div>
              {!s.is_current && (
                <Button
                  size="sm"
                  variant="secondary"
                  loading={busy === s.jti}
                  disabled={busy !== null && busy !== s.jti}
                  onClick={() => void revoke(s)}
                  aria-label={`Sign out ${describeUserAgent(s.user_agent) ?? 'this session'}`}
                >
                  Sign out
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap', marginTop: space['4'] }}>
        <Button
          variant="secondary"
          onClick={() => void revokeOthers()}
          loading={busy === 'others'}
          disabled={others.length === 0 || (busy !== null && busy !== 'others')}
        >
          Sign out everywhere else
        </Button>
        {notice && (
          <span role={notice.tone === 'error' ? 'alert' : 'status'} style={{ ...muted, color: notice.tone === 'error' ? c.error : c.textSecondary }}>
            {notice.text}
          </span>
        )}
      </div>
    </Card>
  );
}
