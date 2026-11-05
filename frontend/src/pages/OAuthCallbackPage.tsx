import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { isAxiosError } from 'axios';
import { useAuth } from '../contexts/AuthContext';
import { AuthShell, AuthError } from '../components/auth/AuthShell';
import { MfaCodeStep } from '../components/auth/MfaCodeStep';
import { Spinner } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { apiErrorMessage } from '../utils/apiError';
import { providerName } from '../utils/accountSecurity';
import { forgetSignInDestination, recallSignInState } from '../utils/signInReturn';
import { fonts, fontSize, fontWeight, space } from '../theme';

/**
 * `/login/oauth/:provider/callback` (T-5.4.5): where Google or GitHub sends
 * the browser back. Hands the provider's `code` and `state` to the server
 * once (the state is single-use), drops them from the address bar, and
 * either signs in or, for an account with two-step verification on, asks
 * for the code. A refusal at the provider comes back as `?error=`.
 *
 * The page the reader wanted waited in this tab's storage during the trip to
 * the provider. It goes back into the router state, where `PublicOnlyRoute`
 * reads it, before the exchange starts: a token that arrived first would send
 * the reader to `/`.
 */
export function OAuthCallbackPage() {
  const c = useColors();
  const { provider = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { completeOAuth } = useAuth();
  const started = useRef(false);
  const exchanged = useRef(false);
  const name = providerName(provider);
  // Read once: the effect below drops them from the address bar.
  const [answer] = useState(() => {
    const params = new URLSearchParams(location.search);
    return { denied: params.get('error'), code: params.get('code'), state: params.get('state') };
  });
  const [error, setError] = useState<string | null>(() => {
    if (answer.denied) {
      return answer.denied === 'access_denied'
        ? `You cancelled at ${name}, so you are not signed in.`
        : `${name} did not sign you in (${answer.denied}).`;
    }
    if (!answer.code || !answer.state) return `This page needs the answer ${name} sends back. Start again from the sign-in page.`;
    return null;
  });
  const [mfaToken, setMfaToken] = useState<string | null>(null);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    // The code is a one-time credential: keep it out of history.
    navigate(location.pathname, { replace: true, state: recallSignInState() });
    forgetSignInDestination();
  }, [location.pathname, navigate]);

  useEffect(() => {
    // Waits for the address above: this render has the destination in its state.
    if (exchanged.current || location.search) return;
    const { denied, code, state } = answer;
    if (denied || !code || !state) return;
    exchanged.current = true;
    completeOAuth(provider, code, state)
      .then((result) => {
        if (result.status === 'mfa_required') setMfaToken(result.mfaToken);
      })
      .catch((err) => {
        setError(
          isAxiosError(err) && err.response?.status === 403
            ? apiErrorMessage(err, `${name} had not verified that email address.`)
            : `Signing in with ${name} did not work. Start again from the sign-in page.`,
        );
      });
  }, [answer, completeOAuth, location.search, name, provider]);

  if (mfaToken) {
    return (
      <AuthShell title="Two-step verification">
        <MfaCodeStep
          mfaToken={mfaToken}
          onStartOver={() => navigate('/login', { replace: true, state: location.state })}
        />
      </AuthShell>
    );
  }

  return (
    <AuthShell title={`Signing in with ${name}`}>
      {error ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'], textAlign: 'center' }}>
          <AuthError message={error} />
          <Link to="/login" state={location.state} style={{ color: c.accent, fontWeight: fontWeight.semibold, textDecoration: 'none', fontFamily: fonts.ui }}>
            Back to sign in
          </Link>
        </div>
      ) : (
        <div
          role="status"
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: space['3'], fontFamily: fonts.ui, fontSize: fontSize.base, color: c.textSecondary }}
        >
          <Spinner size={18} /> Finishing sign-in…
        </div>
      )}
    </AuthShell>
  );
}
