import api from './api';

/** `NotificationResponse` (S-8.3.3). Times are naive UTC. */
export interface AppNotification {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  href: string | null;
  read_at: string | null;
  created_at: string;
}

export interface NotificationList {
  items: AppNotification[];
  unread: number;
}

export const notificationsApi = {
  list: () => api.get<NotificationList>('/notifications').then((r) => r.data),
  markRead: (id: string, read = true) =>
    api.patch<AppNotification>(`/notifications/${id}`, { read }).then((r) => r.data),
  readAll: () => api.post<{ marked: number }>('/notifications/read-all').then((r) => r.data),
};
