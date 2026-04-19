import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

export function RegisterPage() {
  const navigate = useNavigate();
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
    <AuthShell title="Create your account">
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
            autoComplete="new-password"
            placeholder="At least 8 characters"
            minLength={8}
          />
        </Field>
        <Field label="Confirm Password">
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            autoComplete="new-password"
            placeholder="Repeat your password"
            minLength={8}
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
          {isLoading ? 'Creating account...' : 'Create Account'}
        </button>
        {error && <p style={{ color: '#ef4444', margin: 0 }}>{error}</p>}
      </form>
      <p style={{ marginTop: '1.5rem', color: '#64748b', fontSize: '0.9rem' }}>
        Already have an account?{' '}
        <Link to="/login" style={{ color: '#667eea', fontWeight: 600 }}>Sign in</Link>
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
