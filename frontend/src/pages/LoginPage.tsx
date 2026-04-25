import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { AuthShell, AuthError } from '../components/auth/AuthShell';
import { Button, FormField, Input } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, space } from '../theme';

interface LocationState {
  from?: { pathname: string };
}

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const c = useColors();
  const { login, isLoading } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const redirectTo = (location.state as LocationState | null)?.from?.pathname ?? '/submit';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await login(email, password);
      navigate(redirectTo, { replace: true });
    } catch (err) {
      const detail = extractError(err);
      setError(detail ?? 'Login failed. Check your credentials and try again.');
    }
  };

  return (
    <AuthShell title="Welcome back to your library.">
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
        <FormField label="Email" required>
          {(id) => (
            <Input
              id={id}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              placeholder="you@example.com"
            />
          )}
        </FormField>
        <FormField label="Password" required>
          {(id) => (
            <Input
              id={id}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              placeholder="Your password"
            />
          )}
        </FormField>
        <Button type="submit" loading={isLoading} fullWidth style={{ marginTop: space['2'] }}>
          {isLoading ? 'Signing in…' : 'Sign in'}
        </Button>
        {error && <AuthError message={error} />}
      </form>
      <p
        style={{
          marginTop: space['5'],
          marginBottom: 0,
          color: c.textSecondary,
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          textAlign: 'center',
        }}
      >
        New here?{' '}
        <Link
          to="/register"
          style={{
            color: c.accent,
            fontWeight: fontWeight.semibold,
            textDecoration: 'none',
          }}
        >
          Begin your first shelf
        </Link>
      </p>
    </AuthShell>
  );
}

function extractError(err: unknown): string | null {
  if (typeof err === 'object' && err !== null) {
    const maybe = err as { response?: { data?: { detail?: unknown; message?: unknown } }; message?: string };
    const detail = maybe.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    const message = maybe.response?.data?.message;
    if (typeof message === 'string') return message;
    if (maybe.message) return maybe.message;
  }
  return null;
}
