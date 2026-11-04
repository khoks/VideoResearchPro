import api from './api';

/**
 * E-5.4's account endpoints: sessions (T-5.4.7), two-step verification
 * (T-5.4.6), the audit log (T-5.4.4), password change (T-5.4.14) and reset
 * (T-5.4.3), and OAuth (T-5.4.5). The sign-in calls themselves live in
 * AuthContext.
 */

/** `GET /auth/sessions` row. */
export interface SessionInfo {
  id: string;
  jti: string;
  created_at: string;
  last_used_at: string;
  revoked_at: string | null;
  ip_address: string | null;
  user_agent: string | null;
  is_current: boolean;
  /** When the session's token stops working. */
  expires_at?: string | null;
  /** Not revoked and not expired. */
  active?: boolean;
}

/** `GET /auth/audit-log` row. */
export interface AuditLogEntry {
  id: string;
  event: string;
  ip_address: string | null;
  user_agent: string | null;
  metadata_json: string | null;
  created_at: string;
}

export interface MfaEnrollment {
  secret: string;
  provisioning_uri: string;
}

/** Rows on one page of account activity. */
export const ACTIVITY_PAGE_SIZE = 20;

/**
 * Still usable: the server says so, or (an older server without `active`)
 * it was never revoked.
 */
export function isLiveSession(s: SessionInfo): boolean {
  return s.active ?? s.revoked_at === null;
}

export const accountSecurityApi = {
  sessions: () => api.get<SessionInfo[]>('/auth/sessions').then((r) => r.data),
  revokeSession: (jti: string) =>
    api.delete<{ revoked: boolean }>(`/auth/sessions/${encodeURIComponent(jti)}`).then((r) => r.data),
  revokeOtherSessions: () =>
    api.delete<{ revoked_count: number }>('/auth/sessions', { params: { keep_current: true } }).then((r) => r.data),

  /**
   * One page of account and security events, newest first. Asks for one row
   * more than a page so the pager knows whether an older page exists.
   */
  activity: async (page: number) => {
    const { data } = await api.get<AuditLogEntry[]>('/auth/audit-log', {
      params: { scope: 'account', limit: ACTIVITY_PAGE_SIZE + 1, offset: page * ACTIVITY_PAGE_SIZE },
    });
    return { items: data.slice(0, ACTIVITY_PAGE_SIZE), hasOlder: data.length > ACTIVITY_PAGE_SIZE };
  },

  mfaStatus: () => api.get<{ enabled: boolean }>('/auth/mfa/status').then((r) => r.data),
  mfaEnroll: () => api.post<MfaEnrollment>('/auth/mfa/enroll').then((r) => r.data),
  mfaVerifyEnrollment: (code: string) =>
    api
      .post<{ enabled: boolean; recovery_codes: string[] }>('/auth/mfa/verify-enrollment', { code })
      .then((r) => r.data),
  mfaDisable: (code: string) => api.delete<{ disabled: boolean }>('/auth/mfa', { data: { code } }).then((r) => r.data),

  /**
   * T-5.4.14: the server signs out every other session and keeps this one.
   * A refusal is a 400 or 429 whose `detail` says why, never a 401.
   */
  changePassword: (currentPassword: string, newPassword: string) =>
    api
      .post<{ message: string; sessions_revoked: number }>('/auth/password/change', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      .then((r) => r.data),

  /** Always the same generic answer; the code goes by email or the server log. */
  requestPasswordReset: (email: string) => api.post('/auth/password-reset/request', { email }).then(() => undefined),
  confirmPasswordReset: (token: string, newPassword: string) =>
    api.post('/auth/password-reset/confirm', { token, new_password: newPassword }).then(() => undefined),

  /** Names of the OAuth providers this install has set up, and nothing else. */
  oauthProviders: () => api.get<{ providers: string[] }>('/auth/oauth/providers').then((r) => r.data.providers),
  oauthStart: (provider: string, redirectUri: string) =>
    api
      .get<{ authorize_url: string }>(`/auth/oauth/${encodeURIComponent(provider)}/start`, {
        params: { redirect_uri: redirectUri },
      })
      .then((r) => r.data.authorize_url),
};
