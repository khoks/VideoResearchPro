import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { createBatchLoader } from '../utils/batchLoader';

export interface VideoChannel {
  channel_id: string;
  channel_name: string;
}

/** `GET /library/video-channels` (S-8.7.4): visible cited videos → channel. */
const loadVideoChannel = createBatchLoader<VideoChannel>((ids) =>
  api
    .get<Record<string, VideoChannel>>('/library/video-channels', { params: { video_ids: ids.join(',') } })
    .then((r) => r.data),
);

/** The channel of a cited video, if the reader can see the video. Batched
 * across every chip on screen into one request. */
export function useVideoChannel(videoId: string | null) {
  return useQuery({
    queryKey: ['videoChannel', videoId],
    queryFn: () => loadVideoChannel(videoId!),
    enabled: !!videoId,
    staleTime: 5 * 60_000,
    retry: false,
  });
}
