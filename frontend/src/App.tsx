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
import { AuthProvider } from './contexts/AuthContext';
import { globalErrorToastMessage } from './utils/apiError';

function toastError(error: unknown): void {
  // Null for errors the page already shows where the action started.
  const message = globalErrorToastMessage(error);
  if (message) useJobStore.getState().pushToast('error', message);
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5000 },
  },
  queryCache: new QueryCache({ onError: toastError }),
  mutationCache: new MutationCache({ onError: toastError }),
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
        <ToastContainer />
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
