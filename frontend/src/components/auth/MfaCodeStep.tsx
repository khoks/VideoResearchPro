import { useState } from 'react';
import { isAxiosError } from 'axios';
import { useAuth } from '../../contexts/AuthContext';
import { Button, FormField, Input } from '../primitives';
import { AuthError } from './AuthShell';
import { useColors } from '../../hooks/useTheme';
import { apiErrorMessage } from '../../utils/apiError';
import { fonts, fontSize, lineHeight, space } from '../../theme';

export interface MfaCodeStepProps {
  /** The five-minute ticket from the first step (`/auth/login` or an OAuth callback). */
  mfaToken: string;
  /** The address typed at the first step, when there was one. */
  email?: string;
  /** Back to the first step: the ticket expired or the reader changed their mind. */
  onStartOver: () => void;
}

// routers/mfa.py: TICKET_EXPIRED_DETAIL, TICKET_EXHAUSTED_DETAIL.
const EXPIRED_DETAIL = 'Invalid or expired MFA session';
const EXHAUSTED_DETAIL = 'Too many codes tried for this sign-in. Start over and sign in again.';

/**
 * The second sign-in step (T-5.4.6): a code from the authenticator app, or
 * one of the recovery codes shown when two-step verification was turned on.
 * Both go to `POST /auth/login/mfa`; a recovery code works once. The ticket
 * takes five codes (T-5.4.13); after that even the right one is refused, so
 * this step sends the reader back to the first one. A code that works sets the
 * session, and `PublicOnlyRoute` takes it from there.
 */
export function MfaCodeStep({ mfaToken, email, onStartOver }: MfaCodeStepProps) {
  const c = useColors();
  const { completeMfa, isLoading } = useAuth();
  const [code, setCode] = useState('');
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const value = useRecovery ? code.trim() : code.replace(/\s+/g, '');
    try {
      await completeMfa(mfaToken, value, email);
    } catch (err) {
      const detail = isAxiosError(err) ? err.response?.data?.detail : undefined;
      if (detail === EXPIRED_DETAIL) {
        setExpired(true);
        setError('This sign-in timed out. Start over and enter your password again.');
        return;
      }
      if (detail === EXHAUSTED_DETAIL) {
        setExpired(true);
        setError('Too many codes tried. Start over and enter your password again.');
        return;
      }
      setError(
        isAxiosError(err) && err.response?.status === 401
          ? useRecovery
            ? 'That recovery code did not work. Each one works only once.'
            : 'That code did not work. Check the time on your phone and try the newest code.'
          : apiErrorMessage(err, 'Could not check the code. Try again.'),
      );
    }
  };

  const toggle = () => {
    setUseRecovery((r) => !r);
    setCode('');
    setError(null);
  };

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }} aria-label="Two-step verification">
      <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal }}>
        {useRecovery
          ? 'Enter one of the recovery codes you saved when you turned on two-step verification.'
          : 'Enter the 6-digit code from your authenticator app.'}
      </p>
      <FormField label={useRecovery ? 'Recovery code' : 'Authentication code'} required>
        {(id) => (
          <Input
            id={id}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            autoFocus
            disabled={expired}
            minLength={6}
            maxLength={20}
            autoComplete={useRecovery ? 'off' : 'one-time-code'}
            inputMode={useRecovery ? 'text' : 'numeric'}
            placeholder={useRecovery ? 'e.g. 3F9A1C0B7D' : '123456'}
            style={{ fontFamily: fonts.mono, letterSpacing: '0.12em' }}
          />
        )}
      </FormField>
      {expired ? (
        <Button type="button" onClick={onStartOver} fullWidth>
          Start over
        </Button>
      ) : (
        <Button type="submit" loading={isLoading} fullWidth>
          {isLoading ? 'Checking…' : 'Verify and sign in'}
        </Button>
      )}
      {error && <AuthError message={error} />}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: space['2'], flexWrap: 'wrap' }}>
        {!expired && (
          <Button type="button" variant="tertiary" size="sm" onClick={toggle}>
            {useRecovery ? 'Use the authenticator app instead' : 'Use a recovery code instead'}
          </Button>
        )}
        <Button type="button" variant="tertiary" size="sm" onClick={onStartOver} style={{ marginLeft: 'auto' }}>
          Back to sign in
        </Button>
      </div>
    </form>
  );
}
