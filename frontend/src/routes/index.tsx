import { createBrowserRouter, Navigate, Outlet, useLocation } from 'react-router-dom';
import { AppLayout } from '../layouts/AppLayout';
import { SubmitJobPage } from '../pages/SubmitJobPage';
import { JobsListPage } from '../pages/JobsListPage';
import { JobDetailPage } from '../pages/JobDetailPage';
import { LibraryQAPage } from '../pages/LibraryQAPage';
import { LoginPage } from '../pages/LoginPage';
import { RegisterPage } from '../pages/RegisterPage';
import { useAuth } from '../contexts/AuthContext';

function LibraryPagePlaceholder() {
  return <div>Library</div>;
}

function ProtectedRoute() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <Outlet />;
}

function PublicOnlyRoute() {
  const { isAuthenticated } = useAuth();
  if (isAuthenticated) {
    return <Navigate to="/submit" replace />;
  }
  return <Outlet />;
}

export const router = createBrowserRouter([
  {
    element: <PublicOnlyRoute />,
    children: [
      { path: '/login', element: <LoginPage /> },
      { path: '/register', element: <RegisterPage /> },
    ],
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        path: '/',
        element: <AppLayout />,
        children: [
          { index: true, element: <Navigate to="/submit" replace /> },
          { path: 'submit', element: <SubmitJobPage /> },
          { path: 'jobs', element: <JobsListPage /> },
          { path: 'jobs/:jobId', element: <JobDetailPage /> },
          { path: 'library', element: <LibraryPagePlaceholder /> },
          { path: 'library/qa', element: <LibraryQAPage /> },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
