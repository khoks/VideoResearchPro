import api from './api';

export interface Channel {
  id: string;
  channel_id: string;
  name: string;
  url: string | null;
  subscriber_count: number | null;
  video_count: number;
  subscribed: boolean;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChannelSyncResponse {
  job_id: string;
  status: string;
}

export const channelsApi = {
  list: () => api.get<Channel[]>('/channels').then(r => r.data),
  get: (id: string) => api.get<Channel>(`/channels/${id}`).then(r => r.data),
  subscribe: (id: string) =>
    api.post<Channel>(`/channels/${id}/subscribe`).then(r => r.data),
  unsubscribe: (id: string) =>
    api.post<Channel>(`/channels/${id}/unsubscribe`).then(r => r.data),
  sync: (id: string) =>
    api.post<ChannelSyncResponse>(`/channels/${id}/sync`).then(r => r.data),
};
