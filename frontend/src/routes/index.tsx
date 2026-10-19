import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate, Outlet, useLocation } from 'react-router-dom';
import { AppLayout } from '../layouts/AppLayout';
import { MarketingLayout } from '../pages/marketing/MarketingLayout';
import { LandingPage } from '../pages/marketing/LandingPage';
import { PricingPage } from '../pages/marketing/PricingPage';
import { SubmitJobPage } from '../pages/SubmitJobPage';
import { JobsListPage } from '../pages/JobsListPage';
import { JobDetailPage } from '../pages/JobDetailPage';
import { ReportReaderPage } from '../pages/ReportReaderPage';
import { KnowledgeReaderPage } from '../pages/KnowledgeReaderPage';
import { OutputReaderPage } from '../pages/OutputReaderPage';
import { LibraryPage } from '../pages/LibraryPage';
import { LibraryQAPage } from '../pages/LibraryQAPage';
import { ChannelPage } from '../pages/ChannelPage';
import { ShelvesPage } from '../pages/ShelvesPage';
import { ShelfPage } from '../pages/ShelfPage';
import { TemplatesPage } from '../pages/TemplatesPage';
import { QAHistoryChatPage } from '../pages/QAHistoryChatPage';
import { ExportsPage } from '../pages/ExportsPage';
import { NotesPage } from '../pages/NotesPage';
import { LoginPage } from '../pages/LoginPage';
import { RegisterPage } from '../pages/RegisterPage';
import { SubscriptionPage } from '../pages/SubscriptionPage';
import { AIModelsPage } from '../pages/AIModelsPage';
import { EchoPage } from '../pages/EchoPage';
import { EchoInboxPage } from '../pages/EchoInboxPage';
import { AuthorPage } from '../pages/AuthorPage';
import { WelcomePage } from '../pages/WelcomePage';
import { OnboardingGate } from '../components/onboarding/OnboardingGate';
import { useAuth } from '../contexts/AuthContext';
import { Spinner } from '../components/primitives';

// The library map pulls in sigma, graphology and a layout worker: its own chunk (S-8.9.2).
const GraphPage = lazy(() => import('../pages/GraphPage'));

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
    // `/` decides between the wizard and the submit page (S-8.10.1).
    return <Navigate to="/" replace />;
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
          // S-8.10.1: a new account goes to the wizard, everyone else to /submit.
          { index: true, element: <OnboardingGate /> },
          { path: 'welcome', element: <WelcomePage /> },
          { path: 'submit', element: <SubmitJobPage /> },
          { path: 'jobs', element: <JobsListPage /> },
          { path: 'jobs/:jobId', element: <JobDetailPage /> },
          { path: 'reports/:jobId', element: <ReportReaderPage /> },
          { path: 'knowledge/:videoId', element: <KnowledgeReaderPage /> },
          { path: 'author/outputs/:outputId', element: <OutputReaderPage /> },
          { path: 'library', element: <LibraryPage /> },
          { path: 'library/qa', element: <LibraryQAPage /> },
          {
            path: 'library/graph',
            element: (
              <Suspense fallback={<Spinner label="Loading the library map" />}>
                <GraphPage />
              </Suspense>
            ),
          },
          { path: 'library/channels/:channelId', element: <ChannelPage /> },
          { path: 'shelves', element: <ShelvesPage /> },
          { path: 'shelves/:shelfId', element: <ShelfPage /> },
          { path: 'templates', element: <TemplatesPage /> },
          { path: 'qa-history', element: <QAHistoryChatPage /> },
          { path: 'exports', element: <ExportsPage /> },
          { path: 'notes', element: <NotesPage /> },
          { path: 'author', element: <AuthorPage /> },
          { path: 'echo', element: <EchoPage /> },
          { path: 'echo/inbox', element: <EchoInboxPage /> },
          { path: 'account/subscription', element: <SubscriptionPage /> },
          { path: 'account/ai-models', element: <AIModelsPage /> },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
