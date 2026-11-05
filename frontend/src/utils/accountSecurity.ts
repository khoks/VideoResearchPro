/**
 * Pure helpers for the account security page and the sign-in flows: how a
 * session's device reads, what an audit event says, which paths are the
 * public sign-in pages. Kept out of the components so each is unit-tested.
 */

/**
 * The server writes UTC and SQLite hands it back without a zone
 * (`2026-11-03T10:00:00`), which `new Date` would read as local time.
 * A value that names its zone is left alone.
 */
export function parseServerDate(value: string): Date {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  return new Date(hasZone ? value : `${value}Z`);
}

export function formatWhen(value: string): string {
  return parseServerDate(value).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** "Active 5 minutes ago" from a session's `last_used_at`. */
export function lastActiveLabel(value: string, now: Date = new Date()): string {
  const minutes = Math.round((now.getTime() - parseServerDate(value).getTime()) / 60_000);
  if (!Number.isFinite(minutes) || minutes < 2) return 'Active just now';
  if (minutes < 60) return `Active ${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `Active ${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
  const days = Math.round(hours / 24);
  return `Active ${days} ${days === 1 ? 'day' : 'days'} ago`;
}

/**
 * "Firefox on Windows" from a User-Agent header, or null when it names
 * neither. A summary for people, never a security decision: the header is
 * whatever the client sent.
 */
export function describeUserAgent(ua: string | null | undefined): string | null {
  if (!ua) return null;
  const browser =
    /Edg(?:e|A|iOS)?\//.test(ua) ? 'Edge'
    : /OPR\/|Opera/.test(ua) ? 'Opera'
    : /Firefox\/|FxiOS\//.test(ua) ? 'Firefox'
    : /Chrome\/|CriOS\//.test(ua) ? 'Chrome'
    : /Safari\//.test(ua) && /Version\//.test(ua) ? 'Safari'
    : null;
  const os =
    /iPhone|iPad|iPod/.test(ua) ? 'iOS'
    : /Android/.test(ua) ? 'Android'
    : /Windows/.test(ua) ? 'Windows'
    : /Mac OS X|Macintosh/.test(ua) ? 'macOS'
    : /CrOS/.test(ua) ? 'ChromeOS'
    : /Linux/.test(ua) ? 'Linux'
    : null;
  if (browser && os) return `${browser} on ${os}`;
  return browser ?? os;
}

/** The shortest new password the reset and change forms accept. */
export const MIN_PASSWORD = 8;

/** A TOTP key in fours, the way authenticator apps show one to type. */
export function groupKey(secret: string): string {
  return secret.replace(/\s+/g, '').replace(/(.{4})(?=.)/g, '$1 ');
}

const PROVIDER_NAMES: Record<string, string> = { google: 'Google', github: 'GitHub' };

export function providerName(provider: string): string {
  return PROVIDER_NAMES[provider] ?? provider.charAt(0).toUpperCase() + provider.slice(1);
}

/** Where a provider sends the browser back after sign-in. */
export function oauthRedirectUri(origin: string, provider: string): string {
  return `${origin}/login/oauth/${encodeURIComponent(provider)}/callback`;
}

export interface AuditEntryLike {
  event: string;
  metadata_json: string | null;
}

function metadataOf(entry: AuditEntryLike): Record<string, unknown> {
  if (!entry.metadata_json) return {};
  try {
    const parsed: unknown = JSON.parse(entry.metadata_json);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

/** What an account-activity row says, in words. */
export function describeAuditEvent(entry: AuditEntryLike): string {
  const meta = metadataOf(entry);
  const provider = typeof meta.provider === 'string' ? providerName(meta.provider) : null;
  switch (entry.event) {
    case 'user_registered':
      return 'Account created';
    case 'login_success':
      if (meta.requires_mfa) return provider ? `Signed in with ${provider}; two-step code requested` : 'Password accepted; two-step code requested';
      return provider ? `Signed in with ${provider}` : 'Signed in';
    case 'login_failure':
      if (meta.reason === 'oauth_email_unverified') return `Sign-in refused: ${provider ?? 'the provider'} had not verified the email`;
      if (meta.reason === 'oauth_failure') return `Sign-in with ${provider ?? 'a provider'} failed`;
      return 'Failed sign-in attempt';
    case 'login_locked_out':
      return 'Sign-in refused while the account was locked';
    case 'account_locked':
      return 'Account locked after repeated failed sign-ins';
    case 'account_unlocked':
      return 'Account unlocked';
    case 'password_reset_requested':
      return 'Password reset code requested';
    case 'password_reset_completed':
      return 'Password reset';
    case 'password_reset_invalid_token':
      return 'Password reset with an invalid code';
    case 'password_changed':
      return 'Password changed';
    case 'password_change_failed':
      return meta.reason === 'locked_out'
        ? 'Password change refused while the account was locked'
        : 'Password change refused: wrong current password';
    case 'logout':
      return 'Signed out';
    case 'session_revoked':
      return 'Signed out a session';
    case 'sessions_revoked_all':
      if (meta.reason === 'password_reset') return 'Signed out everywhere after the password reset';
      if (meta.reason === 'password_change') return 'Signed out everywhere else after the password change';
      return meta.keep_current ? 'Signed out everywhere else' : 'Signed out everywhere';
    case 'mfa_enrolled':
      return 'Two-step verification setup started';
    case 'mfa_enabled':
      return 'Two-step verification turned on';
    case 'mfa_disabled':
      return 'Two-step verification turned off';
    case 'mfa_disable_failed':
      return meta.reason === 'too_many_attempts'
        ? 'Turning off two-step verification stopped after too many wrong codes'
        : 'Turning off two-step verification refused: wrong code';
    case 'mfa_login_success':
      return 'Two-step code accepted';
    case 'mfa_login_failure':
      if (meta.reason === 'invalid_mfa_token') return 'Two-step sign-in expired';
      if (meta.reason === 'too_many_attempts') return 'Two-step sign-in stopped after too many wrong codes';
      if (meta.reason === 'ticket_used') return 'Two-step sign-in repeated after it had finished';
      return 'Wrong two-step code entered';
    case 'mfa_recovery_code_used':
      return 'Recovery code used';
    case 'tier_changed':
      return typeof meta.to_tier === 'string' ? `Plan changed to ${meta.to_tier}` : 'Plan changed';
    case 'echo_exported':
      return 'Echo data exported';
    case 'echo_brain_deleted':
      return 'Echo deleted';
    default: {
      const words = entry.event.replace(/_/g, ' ').trim();
      return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Account event';
    }
  }
}

/** Failed or refused sign-ins, shown with a warning tone. */
export function isWarningEvent(event: string): boolean {
  return [
    'login_failure',
    'login_locked_out',
    'account_locked',
    'mfa_login_failure',
    'mfa_disable_failed',
    'password_reset_invalid_token',
    'password_change_failed',
  ].includes(event);
}
