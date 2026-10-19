import { Navigate } from 'react-router-dom';
import { useOnboarding } from '../../hooks/useOnboarding';
import { Spinner } from '../primitives';

/**
 * The `/` index route (S-8.10.1). A new account, or one part-way through the
 * wizard, goes to `/welcome`; everyone else to `/submit`. If the state cannot
 * be read the app must still open, so an error falls through to `/submit`.
 */
export function OnboardingGate() {
  const { data, isError, isLoading } = useOnboarding();
  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
        <Spinner />
      </div>
    );
  }
  if (isError || !data) return <Navigate to="/submit" replace />;
  return <Navigate to={data.should_onboard ? '/welcome' : '/submit'} replace />;
}
