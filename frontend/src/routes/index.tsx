import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppLayout } from '../layouts/AppLayout';
import { SubmitJobPage } from '../pages/SubmitJobPage';
import { JobsListPage } from '../pages/JobsListPage';
import { JobDetailPage } from '../pages/JobDetailPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/submit" replace /> },
      { path: 'submit', element: <SubmitJobPage /> },
      { path: 'jobs', element: <JobsListPage /> },
      { path: 'jobs/:jobId', element: <JobDetailPage /> },
    ],
  },
]);
