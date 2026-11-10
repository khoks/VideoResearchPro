import { useState } from 'react';
import { isAxiosError } from 'axios';
import { Badge, Button, Card, FormField, Input, Skeleton } from '../primitives';
import { MFA_KEY, useMfaStatus, useRefreshSecurity } from '../../hooks/useAccountSecurity';
import { accountSecurityApi, type MfaEnrollment } from '../../services/accountSecurityApi';
import { useColors } from '../../hooks/useTheme';
import { apiErrorMessage, inlineErrorMessage } from '../../utils/apiError';
import { groupKey } from '../../utils/accountSecurity';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { SectionTitle } from './SectionTitle';

type Step =
  | { kind: 'idle' }
  | { kind: 'setup'; enrollment: MfaEnrollment }
  | { kind: 'codes'; codes: string[] }
  | { kind: 'disabling' };

/**
 * Two-step verification (T-5.4.6). Turning it on: the server makes a TOTP
 * key, shown here as text and as an `otpauth://` link to copy (no QR code:
 * the app bundles no QR library, and the key is not sent anywhere to draw
 * one); a first code from the app confirms it; ten recovery codes are shown
 * once. Turning it off takes a current code or a recovery code.
 *
 * The key and the recovery codes live only in this component's state, never
 * in the query cache or storage, and are dropped when the step ends.
 */
export function TwoStepCard() {
  const c = useColors();
  const [step, setStep] = useState<Step>({ kind: 'idle' });
  // The status line shows only while no setup step is open; then this card
  // says a failed read, and the toast stands aside (T-3.4.1.26).
  const status = useMfaStatus({ inlineErrors: step.kind !== 'setup' && step.kind !== 'codes' });
  const refresh = useRefreshSecurity();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const enabled = status.data?.enabled === true;

  const reset = (next: Step = { kind: 'idle' }) => {
    setStep(next);
    setCode('');
    setError(null);
    setCopied(null);
  };

  const copy = async (value: string, what: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(what);
    } catch {
      setCopied(null);
      setError('Could not copy; select the text and copy it by hand.');
    }
  };

  const begin = async () => {
    setError(null);
    setBusy(true);
    try {
      const enrollment = await accountSecurityApi.mfaEnroll();
      reset({ kind: 'setup', enrollment });
    } catch (err) {
      if (isAxiosError(err) && err.response?.status === 409) {
        // Already on (another tab turned it on): show that.
        void refresh(MFA_KEY);
      } else {
        setError(apiErrorMessage(err, 'Could not start the setup. Try again.'));
      }
    } finally {
      setBusy(false);
      void refresh();
    }
  };

  const confirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { recovery_codes } = await accountSecurityApi.mfaVerifyEnrollment(code.replace(/\s+/g, ''));
      reset({ kind: 'codes', codes: recovery_codes });
      void refresh();
    } catch (err) {
      if (isAxiosError(err) && err.response?.status === 409) {
        // Already on (another tab confirmed it, and showed the codes there): show that.
        reset();
        void refresh(MFA_KEY);
      } else {
        setError(
          isAxiosError(err) && err.response?.status === 400
            ? 'That code did not match. Enter the newest code your app shows for Pratidhvani.'
            : apiErrorMessage(err, 'Could not check the code. Try again.'),
        );
      }
    } finally {
      setBusy(false);
    }
  };

  const finish = () => {
    reset();
    void refresh(MFA_KEY);
  };

  const disable = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await accountSecurityApi.mfaDisable(code.trim());
      reset();
      void refresh(MFA_KEY);
    } catch (err) {
      setError(
        isAxiosError(err) && err.response?.status === 400
          ? 'That code did not work. Use the newest code from your app, or an unused recovery code.'
          : apiErrorMessage(err, 'Could not turn two-step verification off. Try again.'),
      );
    } finally {
      setBusy(false);
    }
  };

  const text: React.CSSProperties = { margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal };
  const mono: React.CSSProperties = { fontFamily: fonts.mono, fontSize: fontSize.sm, color: c.textPrimary, overflowWrap: 'anywhere' };
  const panel: React.CSSProperties = {
    border: `1px solid ${c.border}`,
    borderRadius: radius.md,
    padding: space['3'],
    background: c.surfaceAlt,
    display: 'flex',
    flexDirection: 'column',
    gap: space['2'],
  };
  const errorLine = error && (
    <p role="alert" style={{ ...text, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error }}>
      {error}
    </p>
  );

  // The setup key and the recovery codes come first, ahead of the status
  // query's loading and error states: they live only in this component, so
  // a background refetch that fails (the window-focus refetch when the
  // reader comes back from their password manager, say) must not replace
  // them. The codes are never shown again once this view goes.
  let body: React.ReactNode;
  if (step.kind === 'setup') {
    const { secret, provisioning_uri } = step.enrollment;
    body = (
      <form onSubmit={confirm} aria-label="Set up two-step verification" style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
        <p style={text}>
          1. In your authenticator app (Google Authenticator, 1Password, Authy, or similar), add an account and type in this key,
          or paste the setup link if the app takes one.
        </p>
        <div style={panel}>
          <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>Key</span>
          <span data-secret style={{ ...mono, fontSize: fontSize.base, letterSpacing: '0.08em' }}>
            {groupKey(secret)}
          </span>
          <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap' }}>
            <Button type="button" size="sm" variant="secondary" onClick={() => void copy(secret, 'key')}>
              {copied === 'key' ? 'Key copied' : 'Copy key'}
            </Button>
            <Button type="button" size="sm" variant="tertiary" onClick={() => void copy(provisioning_uri, 'link')}>
              {copied === 'link' ? 'Setup link copied' : 'Copy setup link'}
            </Button>
          </div>
          <details>
            <summary style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, cursor: 'pointer' }}>Show the setup link</summary>
            <span data-uri style={{ ...mono, fontSize: fontSize.xs, display: 'block', marginTop: space['1'] }}>
              {provisioning_uri}
            </span>
          </details>
        </div>
        <p style={text}>2. Enter the 6-digit code the app now shows.</p>
        <FormField label="Code from the app" required>
          {(id) => (
            <Input
              id={id}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              minLength={6}
              maxLength={10}
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="123456"
              style={{ fontFamily: fonts.mono, letterSpacing: '0.12em', maxWidth: 200 }}
            />
          )}
        </FormField>
        {errorLine}
        <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap' }}>
          <Button type="submit" loading={busy}>
            Turn on
          </Button>
          <Button type="button" variant="tertiary" onClick={() => reset()} disabled={busy}>
            Cancel
          </Button>
        </div>
      </form>
    );
  } else if (step.kind === 'codes') {
    body = (
      <div role="status" style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        <p style={{ ...text, color: c.textPrimary, fontWeight: fontWeight.semibold }}>
          Two-step verification is on. Save these recovery codes now: they are not shown again.
        </p>
        <p style={text}>
          If you lose your phone, each code signs you in once in place of the app. Keep them somewhere apart from the phone, such
          as a password manager.
        </p>
        <ol
          aria-label="Recovery codes"
          style={{
            ...panel,
            margin: 0,
            paddingLeft: space['6'],
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
            columnGap: space['5'],
          }}
        >
          {step.codes.map((rc) => (
            <li key={rc} style={mono}>
              {rc}
            </li>
          ))}
        </ol>
        {errorLine}
        <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap' }}>
          <Button type="button" variant="secondary" onClick={() => void copy(step.codes.join('\n'), 'codes')}>
            {copied === 'codes' ? 'Codes copied' : 'Copy codes'}
          </Button>
          <Button type="button" onClick={finish}>
            I have saved them
          </Button>
        </div>
      </div>
    );
  } else if (status.isLoading) {
    body = <Skeleton variant="row" />;
  } else if (status.isError) {
    const failure = inlineErrorMessage(status.error, 'Could not read whether two-step verification is on.');
    body = failure ? (
      <p role="alert" style={{ ...text, color: c.error }}>
        {failure}
      </p>
    ) : null;
  } else if (enabled && step.kind === 'disabling') {
    body = (
      <form onSubmit={disable} aria-label="Turn off two-step verification" style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        <p style={text}>Enter a code from your authenticator app, or an unused recovery code, to turn two-step verification off.</p>
        <FormField label="Code" required>
          {(id) => (
            <Input
              id={id}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              minLength={6}
              maxLength={20}
              autoComplete="one-time-code"
              style={{ fontFamily: fonts.mono, letterSpacing: '0.12em', maxWidth: 240 }}
            />
          )}
        </FormField>
        {errorLine}
        <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap' }}>
          <Button type="submit" variant="danger" loading={busy}>
            Turn off
          </Button>
          <Button type="button" variant="tertiary" onClick={() => reset()} disabled={busy}>
            Keep it on
          </Button>
        </div>
      </form>
    );
  } else if (enabled) {
    body = (
      <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        <p style={text}>
          Signing in asks for a code from your authenticator app after your password, and after Google or GitHub sign-in too.
        </p>
        <div>
          <Button variant="secondary" onClick={() => reset({ kind: 'disabling' })}>
            Turn off two-step verification
          </Button>
        </div>
      </div>
    );
  } else {
    body = (
      <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        <p style={text}>
          Add a code from an authenticator app to every sign-in, so a stolen password alone is not enough to get in.
        </p>
        {errorLine}
        <div>
          <Button onClick={() => void begin()} loading={busy}>
            Set up two-step verification
          </Button>
        </div>
      </div>
    );
  }

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap', marginBottom: space['2'] }}>
        <SectionTitle>Two-step verification</SectionTitle>
        {status.data && step.kind !== 'codes' && (
          <Badge tone={enabled ? 'success' : 'neutral'} size="sm" style={{ marginBottom: space['2'] }}>
            {enabled ? 'On' : 'Off'}
          </Badge>
        )}
      </div>
      {body}
    </Card>
  );
}
