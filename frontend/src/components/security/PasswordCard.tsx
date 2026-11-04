import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, Card, FormField, Input } from '../primitives';
import { SESSIONS_KEY, useRefreshSecurity } from '../../hooks/useAccountSecurity';
import { accountSecurityApi } from '../../services/accountSecurityApi';
import { useColors } from '../../hooks/useTheme';
import { apiErrorMessage } from '../../utils/apiError';
import { MIN_PASSWORD } from '../../utils/accountSecurity';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';
import { SectionTitle } from './SectionTitle';

/**
 * Change the password while signed in (T-5.4.14): the current one and a new
 * one, to `POST /auth/password/change`. The server signs out every other
 * session and keeps this one. "Forgot it?" goes to the reset flow, which is
 * also the only way to set a first password on an account Google or GitHub
 * made: the server answers such an account with a 400 that says so, shown
 * here as it comes.
 *
 * The passwords live only in this component's state and are cleared after a
 * change. Nothing here is a mutation hook: the app's mutation cache toasts
 * every failure, and a wrong password belongs next to the field it is about.
 */
export function PasswordCard() {
  const c = useColors();
  const refresh = useRefreshSecurity();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setChanged(null);
    if (next !== confirm) {
      setError('The new passwords do not match.');
      return;
    }
    if (next.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters for the new password.`);
      return;
    }
    setBusy(true);
    try {
      const { sessions_revoked: n } = await accountSecurityApi.changePassword(current, next);
      setCurrent('');
      setNext('');
      setConfirm('');
      setChanged(
        n > 0
          ? `Password changed. Signed out ${n} other ${n === 1 ? 'session' : 'sessions'}; this one stays signed in.`
          : 'Password changed.',
      );
      void refresh(SESSIONS_KEY);
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not change the password. Try again.'));
      // A refused try is on the activity list too.
      void refresh();
    } finally {
      setBusy(false);
    }
  };

  const text: React.CSSProperties = { margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal };
  const small: React.CSSProperties = { ...text, fontFamily: fonts.ui, fontSize: fontSize.sm };

  return (
    <Card>
      <SectionTitle>Password</SectionTitle>
      <form onSubmit={submit} aria-label="Change your password" style={{ display: 'flex', flexDirection: 'column', gap: space['3'], maxWidth: 420 }}>
        <p style={text}>Changing your password signs out your other sessions. This one stays signed in.</p>
        <FormField label="Current password" required>
          {(id) => (
            <Input id={id} type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required autoComplete="current-password" />
          )}
        </FormField>
        <p style={small}>
          <Link to="/forgot-password" style={{ color: c.accent, fontWeight: fontWeight.semibold, textDecoration: 'none' }}>
            Forgot it?
          </Link>{' '}
          Request a reset code instead. Also the way to set a first password if you signed up with Google or GitHub.
        </p>
        <FormField label="New password" required>
          {(id) => (
            <Input id={id} type="password" value={next} onChange={(e) => setNext(e.target.value)} required autoComplete="new-password" />
          )}
        </FormField>
        <FormField label="New password again" required>
          {(id) => (
            <Input id={id} type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required autoComplete="new-password" />
          )}
        </FormField>
        {error && (
          <p role="alert" style={{ ...small, color: c.error }}>
            {error}
          </p>
        )}
        {changed && (
          <p role="status" style={small}>
            {changed}
          </p>
        )}
        <div>
          <Button type="submit" loading={busy}>
            Change password
          </Button>
        </div>
      </form>
    </Card>
  );
}
