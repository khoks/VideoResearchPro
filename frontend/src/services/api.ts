import axios from 'axios';
import { isPublicAuthPath } from '../utils/accountSecurity';

export const AUTH_TOKEN_KEY = 'videoresearchpro.authToken';

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

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem(AUTH_TOKEN_KEY);
      // Avoid redirect loops if already on an auth page; there a 401 is the
      // page's own answer (wrong password, wrong code, a refused OAuth sign-in).
      if (!isPublicAuthPath(window.location.pathname)) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  },
);

export default api;
