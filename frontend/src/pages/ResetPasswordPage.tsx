import { useState } from 'react';
import { Link } from 'react-router-dom';
import { isAxiosError } from 'axios';
import { AuthShell, AuthError } from '../components/auth/AuthShell';
import { Button, FormField, Input } from '../components/primitives';
import { accountSecurityApi } from '../services/accountSecurityApi';
import { useColors } from '../hooks/useTheme';
import { apiErrorMessage } from '../utils/apiError';
import { MIN_PASSWORD } from '../utils/accountSecurity';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../theme';

/** What the confirm route says about a used, expired or mistyped code. */
const INVALID_CODE_DETAIL = 'Invalid or expired token';

/**
 * `/reset-password` (T-5.4.3): the code from the email (or the server log)
 * and a new password, to `POST /auth/password-reset/confirm`. The code is
 * pasted, never read from the address bar: a secret in a URL lands in
 * history, logs and Referer headers.
 */
export function ResetPasswordPage() {
  const c = useColors();
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    if (password.length < MIN_PASSWORD) {
      setError(`Password must be at least ${MIN_PASSWORD} characters.`);
      return;
    }
    setBusy(true);
    try {
      await accountSecurityApi.confirmPasswordReset(code.trim(), password);
      setDone(true);
      setCode('');
      setPassword('');
      setConfirm('');
    } catch (err) {
      // Not every 400 is about the code: a password that cannot be stored
      // (T-5.4.18) is refused first and leaves the code good, so it shows
      // the server's own sentence.
      const badCode =
        isAxiosError(err) && err.response?.status === 400 && err.response.data?.detail === INVALID_CODE_DETAIL;
      setError(
        badCode
          ? 'That code is not valid any more: it was used, it expired, or it was mistyped. Request a new one.'
          : apiErrorMessage(err, 'Could not reset the password. Try again.'),
      );
    } finally {
      setBusy(false);
    }
  };

  const linkStyle: React.CSSProperties = { color: c.accent, fontWeight: fontWeight.semibold, textDecoration: 'none' };

  if (done) {
    return (
      <AuthShell title="Password updated">
        <div role="status" style={{ display: 'flex', flexDirection: 'column', gap: space['4'], textAlign: 'center' }}>
          <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal }}>
            Your new password works now. Every session on the account has been signed out, so sign in again. If you did not
            ask for this, check the recent activity under Account, Security.
          </p>
          <Link to="/login" style={linkStyle}>
            Sign in
          </Link>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Set a new password">
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
        <FormField label="Reset code" required helperText="Paste the code from the reset email.">
          {(id) => (
            <Input
              id={id}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              minLength={8}
              maxLength={128}
              autoComplete="off"
              spellCheck={false}
              style={{ fontFamily: fonts.mono }}
            />
          )}
        </FormField>
        <FormField label="New password" required helperText={`At least ${MIN_PASSWORD} characters.`}>
          {(id) => (
            <Input
              id={id}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={MIN_PASSWORD}
              maxLength={128}
              autoComplete="new-password"
            />
          )}
        </FormField>
        <FormField label="Confirm new password" required>
          {(id) => (
            <Input
              id={id}
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              minLength={MIN_PASSWORD}
              maxLength={128}
              autoComplete="new-password"
            />
          )}
        </FormField>
        <Button type="submit" loading={busy} fullWidth>
          Set new password
        </Button>
        {error && <AuthError message={error} />}
      </form>
      <p style={{ margin: `${space['5']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.sm, textAlign: 'center', color: c.textMuted }}>
        <Link to="/forgot-password" style={linkStyle}>
          Request a new code
        </Link>
        <span style={{ margin: `0 ${space['2']}` }}>·</span>
        <Link to="/login" style={linkStyle}>
          Back to sign in
        </Link>
      </p>
    </AuthShell>
  );
}
