import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import api, { AUTH_TOKEN_KEY } from '../services/api';
import { clearPendingShares } from '../services/shareTarget';
import { wsClient } from '../services/wsClient';

export interface AuthUser {
  id?: string;
  email: string;
  tier?: 'free' | 'pro' | 'studio';
}

interface AuthResponse {
  access_token: string;
  token_type?: string;
  user?: AuthUser;
}

/** `/auth/login` (or an OAuth callback) for an account with two-step on (T-5.4.6). */
interface MfaRequiredResponse {
  requires_mfa: true;
  mfa_token: string;
  expires_in?: number;
}

/**
 * What a first sign-in step ended in: signed in, or a second factor owed.
 * The mfa token is the five-minute ticket `/auth/login/mfa` exchanges, with
 * a TOTP or recovery code, for the real session.
 */
export type SignInResult =
  | { status: 'signed_in' }
  | { status: 'mfa_required'; mfaToken: string; expiresIn: number };

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  isAuthenticated: boolean;
  /**
   * This tab signed out on purpose and has not signed in since, so the next
   * sign-in starts at `/` rather than on the page that was left.
   */
  signedOutHere: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<SignInResult>;
  /** Second step: the code from the authenticator app, or a recovery code. */
  completeMfa: (mfaToken: string, code: string, email?: string) => Promise<void>;
  /** Exchange the provider's `code` and `state` at the server (T-5.4.5). */
  completeOAuth: (provider: string, code: string, state: string) => Promise<SignInResult>;
  register: (email: string, password: string) => Promise<void>;
  /**
   * Revoke this session at the server (`POST /auth/logout`), then forget it
   * here. A failed call still signs this browser out.
   */
  logout: () => Promise<void>;
}

function isMfaRequired(data: unknown): data is MfaRequiredResponse {
  return !!data && typeof data === 'object' && (data as { requires_mfa?: unknown }).requires_mfa === true
    && typeof (data as { mfa_token?: unknown }).mfa_token === 'string';
}

const USER_STORAGE_KEY = 'videoresearchpro.authUser';

/**
 * How long sign-out waits for the server to revoke the session before it
 * signs this browser out anyway. The shared axios instance has no timeout,
 * so a stalled backend would otherwise leave the browser signed in.
 */
export const LOGOUT_REVOKE_TIMEOUT_MS = 5000;

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function readStoredUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(AUTH_TOKEN_KEY));
  const [user, setUser] = useState<AuthUser | null>(() => readStoredUser());
  const [isLoading, setIsLoading] = useState(false);
  const [signedOutHere, setSignedOutHere] = useState(false);

  // Keep state in sync with storage if another tab logs out.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === AUTH_TOKEN_KEY) {
        setToken(e.newValue);
        if (!e.newValue) setUser(null);
      }
      if (e.key === USER_STORAGE_KEY) {
        setUser(readStoredUser());
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // T-8.3.3.8: the socket outlives every page, so it closes here, on any way
  // a sign-in ends (this tab or another). The layout cannot do it: signing
  // out unmounts the layout, which only drops its listener.
  useEffect(() => {
    if (!token) wsClient.disconnect();
  }, [token]);

  const persistSession = useCallback(async (data: AuthResponse, fallbackEmail: string) => {
    const nextUser: AuthUser = data.user ?? { email: fallbackEmail };
    localStorage.setItem(AUTH_TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(nextUser));
    setToken(data.access_token);
    setUser(nextUser);
    setSignedOutHere(false);
    if (!nextUser.email) {
      // An OAuth sign-in returns only the token; ask who it is for so the
      // sidebar can name the account. Best-effort: the session stands either way.
      try {
        const { data: me } = await api.get<AuthUser>('/auth/me');
        const named: AuthUser = { id: me.id, email: me.email, tier: me.tier };
        localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(named));
        setUser(named);
      } catch {
        /* the email shows after the next sign-in */
      }
    }
  }, []);

  /** A first step's answer: a session to keep, or the second factor to ask for. */
  const settleFirstStep = useCallback(async (data: AuthResponse | MfaRequiredResponse, email: string): Promise<SignInResult> => {
    if (isMfaRequired(data)) {
      return { status: 'mfa_required', mfaToken: data.mfa_token, expiresIn: data.expires_in ?? 300 };
    }
    await persistSession(data, email);
    return { status: 'signed_in' };
  }, [persistSession]);

  const login = useCallback(async (email: string, password: string) => {
    setIsLoading(true);
    try {
      const { data } = await api.post<AuthResponse | MfaRequiredResponse>('/auth/login', { email, password });
      return await settleFirstStep(data, email);
    } finally {
      setIsLoading(false);
    }
  }, [settleFirstStep]);

  const completeMfa = useCallback(async (mfaToken: string, code: string, email = '') => {
    setIsLoading(true);
    try {
      const { data } = await api.post<AuthResponse>('/auth/login/mfa', { mfa_token: mfaToken, code: code.trim() });
      await persistSession(data, email);
    } finally {
      setIsLoading(false);
    }
  }, [persistSession]);

  const completeOAuth = useCallback(async (provider: string, code: string, state: string) => {
    setIsLoading(true);
    try {
      const { data } = await api.get<AuthResponse | MfaRequiredResponse>(
        `/auth/oauth/${encodeURIComponent(provider)}/callback`,
        { params: { code, state } },
      );
      return await settleFirstStep(data, '');
    } finally {
      setIsLoading(false);
    }
  }, [settleFirstStep]);

  const register = useCallback(async (email: string, password: string) => {
    setIsLoading(true);
    try {
      const { data } = await api.post<Partial<AuthResponse>>('/auth/register', { email, password });
      if (data.access_token) {
        await persistSession(data as AuthResponse, email);
      } else {
        // `POST /auth/register` answers with the new user, not a session
        // (routers/auth.py `UserResponse`), so sign in with the same
        // credentials. Storing the absent token left every new account
        // signed out on its first page.
        const { data: session } = await api.post<AuthResponse>('/auth/login', { email, password });
        await persistSession(session, email);
      }
    } finally {
      setIsLoading(false);
    }
  }, [persistSession]);

  const logout = useCallback(async () => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      // T-5.4.7: revoke the session row, so the token stops working even if
      // a copy of it outlives this browser's storage. Bounded twice: axios
      // aborts the request at the timeout, and the race gives up on it even
      // if the transport ignores that, so the `finally` below always runs.
      if (localStorage.getItem(AUTH_TOKEN_KEY)) {
        const gaveUp = new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error('sign-out request timed out')), LOGOUT_REVOKE_TIMEOUT_MS);
        });
        await Promise.race([api.post('/auth/logout', null, { timeout: LOGOUT_REVOKE_TIMEOUT_MS }), gaveUp]);
      }
    } catch {
      /* already revoked, expired, offline or stalled: still sign this browser out */
    } finally {
      clearTimeout(timer);
      localStorage.removeItem(AUTH_TOKEN_KEY);
      localStorage.removeItem(USER_STORAGE_KEY);
      void clearPendingShares();
      setSignedOutHere(true);
      setToken(null);
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    token,
    isAuthenticated: !!token,
    signedOutHere,
    isLoading,
    login,
    completeMfa,
    completeOAuth,
    register,
    logout,
  }), [user, token, signedOutHere, isLoading, login, completeMfa, completeOAuth, register, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
