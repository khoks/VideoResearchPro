import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { signInDestination } from '../utils/signInReturn';

export function ProtectedRoute() {
  const { isAuthenticated, signedOut } = useAuth();
  const location = useLocation();
  if (!isAuthenticated) {
    // Signing out is not being turned away: the next sign-in, perhaps someone
    // else's, starts at `/` and not on the page this reader left.
    return <Navigate to="/login" replace state={signedOut ? undefined : { from: location }} />;
  }
  return <Outlet />;
}

export function PublicOnlyRoute() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  if (isAuthenticated) {
    // The one redirect a sign-in makes (T-5.4.20): the sign-in pages only set
    // the token, because a second redirect beside this one raced it. Without a
    // page to go back to, `/` decides between the wizard and the submit page
    // (S-8.10.1).
    return <Navigate to={signInDestination(location.state)} replace />;
  }
  return <Outlet />;
}
