import api from './api';
import type { FramesResponse } from '../utils/frames';

/**
 * S-1.18.2: frames for a video in the caller's library. Stills are fetched as
 * blobs with the bearer header (report routes take no token in a URL,
 * D-079), so an `<img>` shows them through an object URL.
 */
export const framesApi = {
  list: async (videoId: string): Promise<FramesResponse> => {
    const { data } = await api.get<FramesResponse>(`/videos/${encodeURIComponent(videoId)}/frames`);
    return data;
  },

  imageBlob: async (videoId: string, frameId: string): Promise<Blob> => {
    const { data } = await api.get<Blob>(
      `/videos/${encodeURIComponent(videoId)}/frames/${encodeURIComponent(frameId)}/image`,
      { responseType: 'blob' },
    );
    return data;
  },

  extract: async (videoId: string, force = false): Promise<{ status: string; document_id: string }> => {
    const { data } = await api.post(`/videos/${encodeURIComponent(videoId)}/extract-frames`, null, {
      params: force ? { force: true } : undefined,
    });
    return data;
  },
};
