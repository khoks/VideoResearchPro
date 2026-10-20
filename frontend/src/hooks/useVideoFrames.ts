import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { framesApi } from '../services/framesApi';
import { nearestFrame, type FramesResponse, type VideoFrame } from '../utils/frames';
import type { CitationStill } from '../components/reader/CitationCard';
import type { CitationIndex, ResolvedCitation } from '../components/reader/citations';

const framesKey = (videoId: string) => ['frames', videoId] as const;

/** One video's frames; polls every 5 s while a capture is running. */
export function useVideoFrames(videoId: string | null | undefined) {
  return useQuery<FramesResponse>({
    queryKey: framesKey(videoId ?? ''),
    queryFn: () => framesApi.list(videoId as string),
    enabled: !!videoId,
    staleTime: 60_000,
    refetchInterval: (query) => (query.state.data?.in_progress ? 5_000 : false),
  });
}

export function useExtractFrames(videoId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (force: boolean = false) => framesApi.extract(videoId as string, force),
    onSuccess: () => qc.invalidateQueries({ queryKey: framesKey(videoId ?? '') }),
  });
}

/**
 * Object URLs for frame stills, fetched with the bearer header only when
 * asked for. `request` is safe to call during render (the fetch is
 * scheduled after it); URLs are revoked when the owning component unmounts.
 */
export function useFrameImageLoader() {
  const [urls, setUrls] = useState<Record<string, string>>({});
  const requested = useRef(new Set<string>());
  const created = useRef<string[]>([]);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true; // StrictMode re-mounts after a cleanup
    return () => {
      alive.current = false;
      for (const url of created.current) URL.revokeObjectURL(url);
      created.current = [];
      requested.current.clear();
    };
  }, []);

  const request = useCallback((videoId: string, frameId: string) => {
    if (requested.current.has(frameId)) return;
    requested.current.add(frameId);
    window.setTimeout(() => {
      framesApi
        .imageBlob(videoId, frameId)
        .then((blob) => {
          if (!alive.current) return;
          const url = URL.createObjectURL(blob);
          created.current.push(url);
          setUrls((prev) => ({ ...prev, [frameId]: url }));
        })
        .catch(() => {
          // A missing still just means no picture; it is not retried.
        });
    }, 0);
  }, []);

  return { urls, request };
}

/** Prefetch a small, known set of stills (one video's frames). */
export function useFrameImages(wanted: Array<{ videoId: string; frameId: string }>) {
  const { urls, request } = useFrameImageLoader();
  const key = wanted.map((w) => w.frameId).sort().join(',');
  useEffect(() => {
    for (const w of wanted) request(w.videoId, w.frameId);
    // `key` captures the identity of `wanted`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, request]);
  return urls;
}

function citationVideoId(c: ResolvedCitation): string | null {
  return c.source?.video_id ?? c.videoId ?? null;
}

/**
 * The R1 hook for the reading room's citation card (T-8.8.2.3 / S-1.18.2):
 * the still nearest each cited moment, when the video has frames.
 */
export function useCitationStills(index: CitationIndex | null) {
  const citations = useMemo(() => (index ? Array.from(index.byIndex.values()) : []), [index]);
  const videoIds = useMemo(
    () => Array.from(new Set(citations.map(citationVideoId).filter((v): v is string => !!v))),
    [citations],
  );
  const results = useQueries({
    queries: videoIds.map((id) => ({
      queryKey: framesKey(id),
      queryFn: () => framesApi.list(id),
      staleTime: 60_000,
      retry: false,
    })),
  });
  const framesByVideo = useMemo(() => {
    const map = new Map<string, VideoFrame[]>();
    videoIds.forEach((id, i) => {
      const frames = results[i]?.data?.frames;
      if (frames?.length) map.set(id, frames);
    });
    return map;
    // `results` changes identity every render; its data is what matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoIds, results.map((r) => r.dataUpdatedAt).join(',')]);

  const matches = useMemo(() => {
    const out = new Map<number, { videoId: string; frame: VideoFrame }>();
    for (const c of citations) {
      const vid = citationVideoId(c);
      const frames = vid ? framesByVideo.get(vid) : undefined;
      const frame = frames ? nearestFrame(frames, c.seconds) : null;
      if (vid && frame) out.set(c.index, { videoId: vid, frame });
    }
    return out;
  }, [citations, framesByVideo]);

  // Lazy (verified 2026-10-19): a report cites ~200 moments, and fetching
  // every matched still at load spent the per-user rate limit (60/min on
  // free) and starved the page's other requests. A still loads when its
  // card first asks for it.
  const { urls, request } = useFrameImageLoader();

  return useCallback(
    (citation: ResolvedCitation): CitationStill | null => {
      const m = matches.get(citation.index);
      if (!m) return null;
      const src = urls[m.frame.frame_id];
      if (!src) {
        request(m.videoId, m.frame.frame_id);
        return null;
      }
      return {
        src,
        alt: `On screen at ${m.frame.timestamp_display}${m.frame.description ? `: ${m.frame.description}` : ''}`,
      };
    },
    [matches, urls, request],
  );
}
