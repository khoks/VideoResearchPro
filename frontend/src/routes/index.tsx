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
import { EchoConnectorCallbackPage } from '../pages/EchoConnectorCallbackPage';
import { WelcomePage } from '../pages/WelcomePage';
import { SavedSearchesPage } from '../pages/SavedSearchesPage';
import { OnboardingGate } from '../components/onboarding/OnboardingGate';
import { RouteLoadError } from '../components/common/RouteLoadError';
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

// T-8.8.4.5: pages an account opens now and then, not on the way to a report or
// an answer. Each is its own chunk, so the pages people work in load without them.
const EchoPage = lazy(() => import('../pages/EchoPage').then((m) => ({ default: m.EchoPage })));
const EchoInboxPage = lazy(() => import('../pages/EchoInboxPage').then((m) => ({ default: m.EchoInboxPage })));
const EchoImportPage = lazy(() => import('../pages/EchoImportPage').then((m) => ({ default: m.EchoImportPage })));
const AuthorPage = lazy(() => import('../pages/AuthorPage').then((m) => ({ default: m.AuthorPage })));
const SubscriptionPage = lazy(() => import('../pages/SubscriptionPage').then((m) => ({ default: m.SubscriptionPage })));
const AIModelsPage = lazy(() => import('../pages/AIModelsPage').then((m) => ({ default: m.AIModelsPage })));
const SystemStatusPage = lazy(() => import('../pages/SystemStatusPage').then((m) => ({ default: m.SystemStatusPage })));

// A lazy route's chunk can fail to load where an eager page cannot, so each
// one carries its own error screen, inside the app layout.
function lazyRoute(page: ReactNode, fallback: ReactNode) {
  return {
    element: <Suspense fallback={fallback}>{page}</Suspense>,
    errorElement: <RouteLoadError />,
  };
}

function reader(page: ReactNode, loading: string) {
  return lazyRoute(page, <ReaderLoading label={loading} />);
}

function lazyPage(element: ReactNode, loading: string) {
  return lazyRoute(element, <Spinner label={loading} />);
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
          { path: 'reports/:jobId', ...reader(<ReportReaderPage />, 'Opening the report…') },
          { path: 'knowledge/:videoId', ...reader(<KnowledgeReaderPage />, 'Opening the knowledge report…') },
          { path: 'author/outputs/:outputId', ...reader(<OutputReaderPage />, 'Opening the manuscript…') },
          { path: 'library', element: <LibraryPage /> },
          { path: 'library/qa', element: <LibraryQAPage /> },
          { path: 'library/graph', ...lazyRoute(<GraphPage />, <Spinner label="Loading the library map" />) },
          { path: 'library/channels/:channelId', element: <ChannelPage /> },
          { path: 'shelves', element: <ShelvesPage /> },
          { path: 'shelves/:shelfId', element: <ShelfPage /> },
          { path: 'templates', element: <TemplatesPage /> },
          { path: 'saved-searches', element: <SavedSearchesPage /> },
          { path: 'qa-history', element: <QAHistoryChatPage /> },
          { path: 'exports', element: <ExportsPage /> },
          { path: 'notes', element: <NotesPage /> },
          { path: 'author', ...lazyPage(<AuthorPage />, 'Loading Author Studio') },
          { path: 'echo', ...lazyPage(<EchoPage />, 'Loading Echo') },
          { path: 'echo/inbox', ...lazyPage(<EchoInboxPage />, 'Loading the inbox') },
          { path: 'echo/import', ...lazyPage(<EchoImportPage />, 'Loading the import page') },
          { path: 'echo/connectors/:name/callback', element: <EchoConnectorCallbackPage /> },
          { path: 'account/subscription', ...lazyPage(<SubscriptionPage />, 'Loading your subscription') },
          { path: 'account/ai-models', ...lazyPage(<AIModelsPage />, 'Loading AI models') },
          { path: 'account/security', element: <AccountSecurityPage /> },
          { path: 'account/system', ...lazyPage(<SystemStatusPage />, 'Loading system status') },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
