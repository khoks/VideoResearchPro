import { useState } from 'react';
import { Link } from 'react-router-dom';
import { AuthShell, AuthError } from '../components/auth/AuthShell';
import { Button, FormField, Input } from '../components/primitives';
import { accountSecurityApi } from '../services/accountSecurityApi';
import { useColors } from '../hooks/useTheme';
import { apiErrorMessage } from '../utils/apiError';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../theme';

/**
 * `/forgot-password` (T-5.4.3): ask for a reset code. The answer is the same
 * whether or not the address has an account, and it never carries the code:
 * that goes by email, or, on an install without email set up, to the server
 * log for the operator. So this page says what happens next and never shows
 * anything from the response.
 */
export function ForgotPasswordPage() {
  const c = useColors();
  const [email, setEmail] = useState('');
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await accountSecurityApi.requestPasswordReset(email.trim());
      setSentTo(email.trim());
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not send the request. Try again in a moment.'));
    } finally {
      setBusy(false);
    }
  };

  const text: React.CSSProperties = {
    margin: 0,
    fontFamily: fonts.body,
    fontSize: fontSize.base,
    color: c.textSecondary,
    lineHeight: lineHeight.normal,
  };
  const linkStyle: React.CSSProperties = { color: c.accent, fontWeight: fontWeight.semibold, textDecoration: 'none' };

  if (sentTo) {
    return (
      <AuthShell title="Check for your reset code">
        <div role="status" style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
          <p style={text}>
            If an account uses <strong style={{ color: c.textPrimary }}>{sentTo}</strong>, a reset code is on its way. It works
            once, and only for a short while.
          </p>
          <p style={{ ...text, fontSize: fontSize.sm, color: c.textMuted }}>
            No email? On a self-hosted install without email set up, the code goes to the server log instead: ask whoever runs
            this install.
          </p>
          <Link to="/reset-password" style={{ ...linkStyle, textAlign: 'center' }}>
            I have a code
          </Link>
          <Button type="button" variant="tertiary" onClick={() => setSentTo(null)}>
            Use a different address
          </Button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Reset your password">
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
        <p style={text}>Enter the address you sign in with and we will send a code to set a new password.</p>
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
        <Button type="submit" loading={busy} fullWidth>
          Send a reset code
        </Button>
        {error && <AuthError message={error} />}
      </form>
      <p style={{ ...text, marginTop: space['5'], fontFamily: fonts.ui, fontSize: fontSize.sm, textAlign: 'center' }}>
        <Link to="/reset-password" style={linkStyle}>
          I already have a code
        </Link>
        <span style={{ margin: `0 ${space['2']}`, color: c.textMuted }}>·</span>
        <Link to="/login" style={linkStyle}>
          Back to sign in
        </Link>
      </p>
    </AuthShell>
  );
}
