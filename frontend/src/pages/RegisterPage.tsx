import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { AuthShell, AuthError } from '../components/auth/AuthShell';
import { Button, FormField, Input } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, space } from '../theme';

export function RegisterPage() {
  const navigate = useNavigate();
  const c = useColors();
  const { register, isLoading } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    try {
      await register(email, password);
      navigate('/submit', { replace: true });
    } catch (err) {
      const detail = extractError(err);
      setError(detail ?? 'Registration failed. Try a different email.');
    }
  };

  return (
    <AuthShell title="Begin your personal library.">
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
        <FormField label="Password" required helperText="At least 8 characters.">
          {(id) => (
            <Input
              id={id}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="new-password"
              placeholder="At least 8 characters"
              minLength={8}
            />
          )}
        </FormField>
        <FormField label="Confirm password" required>
          {(id) => (
            <Input
              id={id}
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              autoComplete="new-password"
              placeholder="Repeat your password"
              minLength={8}
            />
          )}
        </FormField>
        <Button type="submit" loading={isLoading} fullWidth style={{ marginTop: space['2'] }}>
          {isLoading ? 'Creating account…' : 'Create account'}
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
        Already curating?{' '}
        <Link
          to="/login"
          style={{
            color: c.accent,
            fontWeight: fontWeight.semibold,
            textDecoration: 'none',
          }}
        >
          Sign in
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
