import { useQuery } from '@tanstack/react-query';
import { libraryApi, type ListVideosParams } from '../services/libraryApi';

export function useLibraryVideos(params?: ListVideosParams) {
  return useQuery({
    queryKey: [
      'libraryVideos',
      params?.search ?? null,
      params?.language ?? null,
      params?.channel_id ?? null,
      params?.transcript_status ?? null,
      params?.sort ?? null,
      params?.limit ?? null,
      params?.offset ?? null,
    ],
    queryFn: () => libraryApi.listVideos(params),
    staleTime: 30_000,
  });
}
