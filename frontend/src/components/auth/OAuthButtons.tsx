import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { accountSecurityApi } from '../../services/accountSecurityApi';
import { Button } from '../primitives';
import { AuthError } from './AuthShell';
import { useColors } from '../../hooks/useTheme';
import { apiErrorMessage } from '../../utils/apiError';
import { oauthRedirectUri, providerName } from '../../utils/accountSecurity';
import { rememberSignInDestination } from '../../utils/signInReturn';
import { fonts, fontSize, space } from '../../theme';

/**
 * "Continue with Google / GitHub" (T-5.4.5), only for the providers this
 * install has set up: `GET /auth/oauth/providers` answers with their names
 * and nothing else. Renders nothing when there are none or the call fails,
 * so an install without OAuth shows the password form alone.
 */
export function OAuthButtons() {
  const c = useColors();
  const location = useLocation();
  const [providers, setProviders] = useState<string[]>([]);
  const [starting, setStarting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    accountSecurityApi
      .oauthProviders()
      .then((names) => {
        if (live) setProviders(names.filter((n) => typeof n === 'string' && n.length > 0));
      })
      .catch(() => {
        /* no buttons: the password form still works */
      });
    return () => {
      live = false;
    };
  }, []);

  if (providers.length === 0) return null;

  const start = async (provider: string) => {
    setError(null);
    setStarting(provider);
    try {
      const url = await accountSecurityApi.oauthStart(provider, oauthRedirectUri(window.location.origin, provider));
      // The server builds this from the provider's configured authorize
      // endpoint; refuse anything that is not a web address.
      if (!/^https?:\/\//i.test(url)) throw new Error('not a web address');
      rememberSignInDestination(location.state);
      window.location.assign(url);
    } catch (err) {
      setError(apiErrorMessage(err, `Could not start signing in with ${providerName(provider)}. Try again.`));
      setStarting(null);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'], marginTop: space['5'] }}>
      <div
        aria-hidden
        style={{ display: 'flex', alignItems: 'center', gap: space['3'], color: c.textMuted, fontFamily: fonts.ui, fontSize: fontSize.xs }}
      >
        <span style={{ flex: 1, height: 1, background: c.border }} />
        or
        <span style={{ flex: 1, height: 1, background: c.border }} />
      </div>
      {providers.map((p) => (
        <Button
          key={p}
          type="button"
          variant="secondary"
          fullWidth
          loading={starting === p}
          disabled={starting !== null && starting !== p}
          onClick={() => void start(p)}
        >
          Continue with {providerName(p)}
        </Button>
      ))}
      {error && <AuthError message={error} />}
    </div>
  );
}
