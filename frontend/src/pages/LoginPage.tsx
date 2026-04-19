import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

interface LocationState {
  from?: { pathname: string };
}

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
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
    <AuthShell title="Sign in to VideoResearchPro">
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <Field label="Email">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            placeholder="you@example.com"
          />
        </Field>
        <Field label="Password">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            placeholder="Your password"
          />
        </Field>
        <button
          type="submit"
          disabled={isLoading}
          style={{
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            color: '#fff', border: 'none', padding: '0.8rem 2rem', borderRadius: 8,
            fontSize: '1rem', fontWeight: 600, cursor: 'pointer', marginTop: '0.5rem',
            opacity: isLoading ? 0.7 : 1,
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
          }}
        >
          {isLoading ? <LoadingSpinner size={18} /> : null}
          {isLoading ? 'Signing in...' : 'Sign In'}
        </button>
        {error && <p style={{ color: '#ef4444', margin: 0 }}>{error}</p>}
      </form>
      <p style={{ marginTop: '1.5rem', color: '#64748b', fontSize: '0.9rem' }}>
        Don&apos;t have an account?{' '}
        <Link to="/register" style={{ color: '#667eea', fontWeight: 600 }}>Create one</Link>
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

function AuthShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2rem',
    }}>
      <div style={{
        background: '#fff',
        borderRadius: 12,
        padding: '2.5rem',
        width: '100%',
        maxWidth: 420,
        boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
      }}>
        <h1 style={{ margin: 0, marginBottom: '0.3rem', color: '#1e293b', fontSize: '1.6rem' }}>
          VideoResearchPro
        </h1>
        <h2 style={{ margin: 0, marginBottom: '1.5rem', color: '#64748b', fontSize: '1rem', fontWeight: 500 }}>
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
      <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#475569' }}>{label}</span>
      {children}
    </label>
  );
}
