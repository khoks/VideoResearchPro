import { createBrowserRouter, Navigate, Outlet, useLocation } from 'react-router-dom';
import { AppLayout } from '../layouts/AppLayout';
import { MarketingLayout } from '../pages/marketing/MarketingLayout';
import { LandingPage } from '../pages/marketing/LandingPage';
import { PricingPage } from '../pages/marketing/PricingPage';
import { SubmitJobPage } from '../pages/SubmitJobPage';
import { JobsListPage } from '../pages/JobsListPage';
import { JobDetailPage } from '../pages/JobDetailPage';
import { LibraryPage } from '../pages/LibraryPage';
import { LibraryQAPage } from '../pages/LibraryQAPage';
import { QAHistoryChatPage } from '../pages/QAHistoryChatPage';
import { ExportsPage } from '../pages/ExportsPage';
import { LoginPage } from '../pages/LoginPage';
import { RegisterPage } from '../pages/RegisterPage';
import { SubscriptionPage } from '../pages/SubscriptionPage';
import { EchoPage } from '../pages/EchoPage';
import { AuthorPage } from '../pages/AuthorPage';
import { useAuth } from '../contexts/AuthContext';

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
  // Truly-public marketing routes — anyone can view, authed or not.
  // Header chrome adapts (Sign in/Get started vs Open app →).
  {
    element: <MarketingLayout />,
    children: [
      { path: '/landing', element: <LandingPage /> },
      { path: '/pricing', element: <PricingPage /> },
    ],
  },
  // Auth pages — public-only (redirect to /submit if already authed).
  {
    element: <PublicOnlyRoute />,
    children: [
      { path: '/login', element: <LoginPage /> },
      { path: '/register', element: <RegisterPage /> },
    ],
  },
  // Authenticated app surface.
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
          { path: 'library', element: <LibraryPage /> },
          { path: 'library/qa', element: <LibraryQAPage /> },
          { path: 'qa-history', element: <QAHistoryChatPage /> },
          { path: 'exports', element: <ExportsPage /> },
          { path: 'author', element: <AuthorPage /> },
          { path: 'echo', element: <EchoPage /> },
          { path: 'account/subscription', element: <SubscriptionPage /> },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
