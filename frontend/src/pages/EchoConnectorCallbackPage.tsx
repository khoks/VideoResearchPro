/**
 * `/echo/connectors/:name/callback` — where a provider sends the browser back
 * after the user approves (S-3.2.1). Posts the code and state to the server
 * with the reader's token (the state is bound to that reader), then returns
 * to the Echo page. A denial at the provider comes back as `?error=`.
 */
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Card, Spinner } from '../components/primitives';
import { useCompleteConnector } from '../hooks/useEcho';
import { useColors } from '../hooks/useTheme';
import { apiErrorMessage } from '../utils/apiError';
import { fonts, fontSize, measure, space } from '../theme';

export function EchoConnectorCallbackPage() {
  const c = useColors();
  const { name = '' } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const complete = useCompleteConnector();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const denied = params.get('error');
    const code = params.get('code');
    const state = params.get('state');
    if (denied) {
      setError(denied === 'access_denied' ? 'You declined on the provider, so nothing was connected.' : `The provider said: ${denied}`);
      return;
    }
    if (!code || !state) {
      setError('This link is missing what the provider sends back. Start again from the Echo page.');
      return;
    }
    complete
      .mutateAsync({ name, code, state })
      .then(() => navigate(`/echo?connected=${encodeURIComponent(name)}`, { replace: true }))
      .catch((e) => setError(apiErrorMessage(e, 'Connecting failed. Start again from the Echo page.')));
  }, [complete, name, navigate, params]);

  return (
    <div style={{ maxWidth: measure.form, margin: `${space['8']} auto` }}>
      <Card>
        {error ? (
          <div role="alert" style={{ fontFamily: fonts.ui, fontSize: fontSize.base, color: c.textPrimary }}>
            <p style={{ margin: `0 0 ${space['3']}` }}>{error}</p>
            <Link to="/echo" style={{ color: c.accent }}>
              Back to Echo
            </Link>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], fontFamily: fonts.ui, color: c.textSecondary }}>
            <Spinner size={18} /> Finishing the connection…
          </div>
        )}
      </Card>
    </div>
  );
}
