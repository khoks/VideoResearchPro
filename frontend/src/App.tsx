import { RouterProvider } from 'react-router-dom';
import {
  QueryCache,
  MutationCache,
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query';
import { router } from './routes';
import { ToastContainer } from './components/common/Toast';
import { useJobStore } from './stores/jobStore';

function extractErrorMessage(error: unknown): string {
  if (!error) return 'An unexpected error occurred.';
  if (typeof error === 'string') return error;
  if (error instanceof Error) return error.message;
  return 'An unexpected error occurred.';
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5000 },
  },
  queryCache: new QueryCache({
    onError: (error) => {
      useJobStore.getState().pushToast('error', extractErrorMessage(error));
    },
  }),
  mutationCache: new MutationCache({
    onError: (error) => {
      useJobStore.getState().pushToast('error', extractErrorMessage(error));
    },
  }),
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <ToastContainer />
    </QueryClientProvider>
  );
}

export default App;
