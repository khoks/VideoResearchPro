import api from './api';

export type TranscriptStatus = 'fetched' | 'pending' | 'unavailable';

export type LibrarySort = 'newest' | 'oldest' | 'longest' | 'shortest';

export interface LibraryVideoResponse {
  id: string;
  video_id: string;
  title: string;
  channel_id: string;
  channel_name: string;
  url: string;
  thumbnail_url: string | null;
  duration_seconds: number;
  published_at: string | null;
  transcript_status: TranscriptStatus | string;
  transcript_language: string | null;
  transcript_word_count: number | null;
  job_count: number;
  job_titles: string[];
}

export interface ListVideosParams {
  search?: string;
  language?: string;
  channel_id?: string;
  transcript_status?: string;
  sort?: LibrarySort;
  limit?: number;
  offset?: number;
}

export const libraryApi = {
  // TODO: if backend adds a paginated wrapper ({items,total,...}), adjust the return type.
  listVideos: (params?: ListVideosParams) =>
    api.get<LibraryVideoResponse[]>('/library/videos', { params }).then(r => r.data),
};
