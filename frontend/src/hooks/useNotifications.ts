import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../contexts/AuthContext';
import { notificationsApi } from '../services/notificationsApi';
import { wsClient } from '../services/wsClient';

export const notificationsKey = ['notifications'] as const;

/**
 * The bell's list (S-8.3.3). Refetched the moment a notification arrives
 * over the WebSocket (`useLiveNotifications`, T-8.3.3.8), and still polled
 * every minute and on focus: the poll is the fallback for a dropped socket
 * or a down Redis.
 */
export function useNotifications() {
  const { isAuthenticated } = useAuth();
  return useQuery({
    queryKey: notificationsKey,
    queryFn: () => notificationsApi.list(),
    enabled: isAuthenticated,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    staleTime: 20_000,
  });
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: notificationsKey }),
  });
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => notificationsApi.readAll(),
    onSuccess: () => void qc.invalidateQueries({ queryKey: notificationsKey }),
  });
}

/**
 * T-8.3.3.8: keep the bell live. While signed in, the shared socket
 * subscribes to this user's notifications and each new one refetches the
 * list (the push carries no text; the list is read over HTTP). Mount once,
 * in the app layout: the bell itself renders twice (sidebar and phone bar).
 * A new sign-in re-subscribes on a socket opened with its own token.
 */
export function useLiveNotifications() {
  const { token } = useAuth();
  const qc = useQueryClient();
  useEffect(() => {
    if (!token) return;
    return wsClient.subscribeNotifications(() => {
      void qc.invalidateQueries({ queryKey: notificationsKey });
    });
  }, [token, qc]);
}
