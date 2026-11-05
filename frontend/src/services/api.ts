import axios, { type InternalAxiosRequestConfig } from 'axios';
import { AUTH_TOKEN_KEY, sessionRefused } from './sessionExpiry';

export { AUTH_TOKEN_KEY };

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (token) {
    config.headers = config.headers ?? {};
    (config.headers as Record<string, string>).Authorization = `Bearer ${token}`;
  }
  return config;
});

/**
 * Where a 401 is not news about the session. On the sign-in calls it is the
 * answer to what was typed (a wrong password, a wrong code, a refused OAuth
 * sign-in), and the page shows it. A sign-out ends the session by itself, and a
 * 401 there must not read as an expiry, which would keep the page (D-140).
 */
const OWN_ANSWER = /^\/auth\/(?:login|logout|register|oauth\/|password-reset\/)/;

function tokenSentWith(config: InternalAxiosRequestConfig | undefined): string | null {
  const header = config?.headers?.Authorization;
  return typeof header === 'string' && header.startsWith('Bearer ') ? header.slice('Bearer '.length) : null;
}

// No navigation here (T-5.4.22): `sessionExpiry.ts` says what happens instead.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401 && !OWN_ANSWER.test(error.config?.url ?? '')) {
      sessionRefused(tokenSentWith(error.config));
    }
    return Promise.reject(error);
  },
);

export default api;
