import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useOnboarding } from '../../hooks/useOnboarding';
import { hasPendingShares, SHARE_REVIEW_PATH } from '../../services/shareTarget';
import { Spinner } from '../primitives';

/**
 * The `/` index route (S-8.10.1). A new account, or one part-way through the
 * wizard, goes to `/welcome`; everyone else to `/submit`. If the state cannot
 * be read the app must still open, so an error falls through to `/submit`.
 *
 * Every way of signing in ends here (T-3.7.6.1), so this is where a share made
 * while signed out is picked up. A second redirect beside this one would race
 * it: the share page lost to `/submit` when both fired.
 */
export function OnboardingGate() {
  const { data, isError, isLoading } = useOnboarding();
  const [sharePending, setSharePending] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    void hasPendingShares().then((waiting) => {
      if (live) setSharePending(waiting);
    });
    return () => {
      live = false;
    };
  }, []);

  if (sharePending) return <Navigate to={SHARE_REVIEW_PATH} replace />;
  if (isLoading || sharePending === null) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
        <Spinner />
      </div>
    );
  }
  if (isError || !data) return <Navigate to="/submit" replace />;
  return <Navigate to={data.should_onboard ? '/welcome' : '/submit'} replace />;
}
