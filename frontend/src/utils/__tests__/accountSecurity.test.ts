import { describe, expect, it } from 'vitest';
import {
  describeAuditEvent,
  describeUserAgent,
  groupKey,
  isPublicAuthPath,
  isWarningEvent,
  lastActiveLabel,
  oauthRedirectUri,
  parseServerDate,
  providerName,
} from '../accountSecurity';

describe('parseServerDate', () => {
  it('reads a zoneless server time as UTC', () => {
    expect(parseServerDate('2026-11-03T10:00:00').toISOString()).toBe('2026-11-03T10:00:00.000Z');
  });
  it('leaves a value that names its zone alone', () => {
    expect(parseServerDate('2026-11-03T10:00:00+02:00').toISOString()).toBe('2026-11-03T08:00:00.000Z');
    expect(parseServerDate('2026-11-03T10:00:00Z').toISOString()).toBe('2026-11-03T10:00:00.000Z');
  });
});

describe('lastActiveLabel', () => {
  const now = new Date('2026-11-03T12:00:00Z');
  it('rounds to minutes, hours and days', () => {
    expect(lastActiveLabel('2026-11-03T11:59:30', now)).toBe('Active just now');
    expect(lastActiveLabel('2026-11-03T11:30:00', now)).toBe('Active 30 minutes ago');
    expect(lastActiveLabel('2026-11-03T09:00:00', now)).toBe('Active 3 hours ago');
    expect(lastActiveLabel('2026-11-01T12:00:00', now)).toBe('Active 2 days ago');
  });
});

describe('describeUserAgent', () => {
  it('names the browser and the system', () => {
    expect(
      describeUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'),
    ).toBe('Chrome on Windows');
    expect(
      describeUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Edg/130.0'),
    ).toBe('Edge on Windows');
    expect(describeUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15')).toBe(
      'Safari on macOS',
    );
    expect(describeUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile Safari/604.1')).toBe(
      'Safari on iOS',
    );
    expect(describeUserAgent('Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0')).toBe('Firefox on Linux');
  });
  it('is null when it names neither', () => {
    expect(describeUserAgent(null)).toBeNull();
    expect(describeUserAgent('python-httpx/0.27')).toBeNull();
  });
});

describe('groupKey', () => {
  it('groups a key in fours', () => {
    expect(groupKey('JBSWY3DPEHPK3PXPABCD')).toBe('JBSW Y3DP EHPK 3PXP ABCD');
    expect(groupKey('ABCDEF')).toBe('ABCD EF');
  });
});

describe('isPublicAuthPath', () => {
  it('covers the sign-in pages, the OAuth return and the reset pages', () => {
    for (const p of ['/login', '/login/oauth/google/callback', '/register', '/forgot-password', '/reset-password']) {
      expect(isPublicAuthPath(p), p).toBe(true);
    }
  });
  it('leaves the app pages to the 401 redirect', () => {
    for (const p of ['/', '/account/security', '/library', '/loginx']) {
      expect(isPublicAuthPath(p), p).toBe(false);
    }
  });
});

describe('OAuth helpers', () => {
  it('names the providers and builds the return address', () => {
    expect(providerName('github')).toBe('GitHub');
    expect(providerName('google')).toBe('Google');
    expect(providerName('gitlab')).toBe('Gitlab');
    expect(oauthRedirectUri('http://localhost:5173', 'google')).toBe('http://localhost:5173/login/oauth/google/callback');
  });
});

describe('describeAuditEvent', () => {
  const e = (event: string, meta?: object) => ({ event, metadata_json: meta ? JSON.stringify(meta) : null });
  it('says what happened, with the detail the metadata carries', () => {
    expect(describeAuditEvent(e('login_success'))).toBe('Signed in');
    expect(describeAuditEvent(e('login_success', { provider: 'github', via: 'oauth' }))).toBe('Signed in with GitHub');
    expect(describeAuditEvent(e('login_success', { requires_mfa: true }))).toBe('Password accepted; two-step code requested');
    expect(describeAuditEvent(e('login_failure', { email: 'a@x.com' }))).toBe('Failed sign-in attempt');
    expect(describeAuditEvent(e('login_failure', { reason: 'oauth_email_unverified', provider: 'google' }))).toBe(
      'Sign-in refused: Google had not verified the email',
    );
    expect(describeAuditEvent(e('sessions_revoked_all', { keep_current: true, revoked_count: 2 }))).toBe('Signed out everywhere else');
    expect(describeAuditEvent(e('sessions_revoked_all', { keep_current: false }))).toBe('Signed out everywhere');
    expect(describeAuditEvent(e('mfa_enabled'))).toBe('Two-step verification turned on');
    expect(describeAuditEvent(e('tier_changed', { to_tier: 'pro' }))).toBe('Plan changed to pro');
  });
  it('falls back to the event name, and survives bad metadata', () => {
    expect(describeAuditEvent(e('something_new'))).toBe('Something new');
    expect(describeAuditEvent({ event: 'login_success', metadata_json: '{not json' })).toBe('Signed in');
  });
  it('marks failed and refused sign-ins as warnings', () => {
    expect(isWarningEvent('login_failure')).toBe(true);
    expect(isWarningEvent('mfa_login_failure')).toBe(true);
    expect(isWarningEvent('login_success')).toBe(false);
  });
});
