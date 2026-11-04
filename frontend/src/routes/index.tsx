import { lazy, Suspense, type ReactNode } from 'react';
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
import { ChannelPage } from '../pages/ChannelPage';
import { ShelvesPage } from '../pages/ShelvesPage';
import { ShelfPage } from '../pages/ShelfPage';
import { TemplatesPage } from '../pages/TemplatesPage';
import { QAHistoryChatPage } from '../pages/QAHistoryChatPage';
import { ExportsPage } from '../pages/ExportsPage';
import { NotesPage } from '../pages/NotesPage';
import { LoginPage } from '../pages/LoginPage';
import { RegisterPage } from '../pages/RegisterPage';
import { ForgotPasswordPage } from '../pages/ForgotPasswordPage';
import { ResetPasswordPage } from '../pages/ResetPasswordPage';
import { OAuthCallbackPage } from '../pages/OAuthCallbackPage';
import { AccountSecurityPage } from '../pages/AccountSecurityPage';
import { SubscriptionPage } from '../pages/SubscriptionPage';
import { AIModelsPage } from '../pages/AIModelsPage';
import { SystemStatusPage } from '../pages/SystemStatusPage';
import { EchoPage } from '../pages/EchoPage';
import { EchoInboxPage } from '../pages/EchoInboxPage';
import { EchoImportPage } from '../pages/EchoImportPage';
import { EchoConnectorCallbackPage } from '../pages/EchoConnectorCallbackPage';
import { AuthorPage } from '../pages/AuthorPage';
import { WelcomePage } from '../pages/WelcomePage';
import { SavedSearchesPage } from '../pages/SavedSearchesPage';
import { OnboardingGate } from '../components/onboarding/OnboardingGate';
import { useAuth } from '../contexts/AuthContext';
import { Spinner } from '../components/primitives';
// Direct, not through `components/reader/index`: the barrel would pull the
// sanitiser and the parsers back into this chunk.
import { ReaderLoading } from '../components/reader/ReaderLoading';

// The library map pulls in sigma, graphology and a layout worker: its own chunk (S-8.9.2).
const GraphPage = lazy(() => import('../pages/GraphPage'));

// T-8.8.4.1: the three readers carry DOMPurify, html-react-parser and
// remark-gfm, which no other page imports; each reader is its own chunk and
// they share one `reader` chunk for those libraries.
// While a reader's chunk loads it shows the line the reader itself shows
// while its data loads, so the two waits read as one.
const ReportReaderPage = lazy(() =>
  import('../pages/ReportReaderPage').then((m) => ({ default: m.ReportReaderPage })),
);
const KnowledgeReaderPage = lazy(() =>
  import('../pages/KnowledgeReaderPage').then((m) => ({ default: m.KnowledgeReaderPage })),
);
const OutputReaderPage = lazy(() =>
  import('../pages/OutputReaderPage').then((m) => ({ default: m.OutputReaderPage })),
);

function reader(page: ReactNode, loading: string) {
  return <Suspense fallback={<ReaderLoading label={loading} />}>{page}</Suspense>;
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
      // T-5.4.5: where Google / GitHub send the browser back.
      { path: '/login/oauth/:provider/callback', element: <OAuthCallbackPage /> },
    ],
  },
  // Password reset (T-5.4.3): open signed in or out, so the Security page
  // can send a signed-in reader here to set a new password.
  { path: '/forgot-password', element: <ForgotPasswordPage /> },
  { path: '/reset-password', element: <ResetPasswordPage /> },
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
          { path: 'reports/:jobId', element: reader(<ReportReaderPage />, 'Opening the report…') },
          { path: 'knowledge/:videoId', element: reader(<KnowledgeReaderPage />, 'Opening the knowledge report…') },
          { path: 'author/outputs/:outputId', element: reader(<OutputReaderPage />, 'Opening the manuscript…') },
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
          { path: 'saved-searches', element: <SavedSearchesPage /> },
          { path: 'qa-history', element: <QAHistoryChatPage /> },
          { path: 'exports', element: <ExportsPage /> },
          { path: 'notes', element: <NotesPage /> },
          { path: 'author', element: <AuthorPage /> },
          { path: 'echo', element: <EchoPage /> },
          { path: 'echo/inbox', element: <EchoInboxPage /> },
          { path: 'echo/import', element: <EchoImportPage /> },
          { path: 'echo/connectors/:name/callback', element: <EchoConnectorCallbackPage /> },
          { path: 'account/subscription', element: <SubscriptionPage /> },
          { path: 'account/ai-models', element: <AIModelsPage /> },
          { path: 'account/security', element: <AccountSecurityPage /> },
          { path: 'account/system', element: <SystemStatusPage /> },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
