/**
 * S-1.18.2: frames captured for a video (R1, D-067), and which one a cited
 * moment refers to.
 */

export interface VideoFrame {
  frame_id: string;
  timestamp_seconds: number;
  timestamp_display: string;
  description: string | null;
  informative: boolean | null;
  status: string;
  width: number | null;
  height: number | null;
  has_image: boolean;
}

export interface FramesResponse {
  document_id: string;
  video_id: string | null;
  /** The install-wide switch (VISUAL_ENABLED); off = no new captures here. */
  visual_enabled: boolean;
  in_progress: boolean;
  frames: VideoFrame[];
}

/**
 * A report's citation link points at the START of the transcript chunk a
 * claim came from, and the frame that chunk described can sit up to a couple
 * of minutes later. A frame slightly before the link still belongs to it.
 */
export const STILL_WINDOW_BEFORE_S = 20;
export const STILL_WINDOW_AFTER_S = 120;

/** Frames worth showing: described, not flagged uninformative, image on disk. */
export function usableFrames(frames: VideoFrame[]): VideoFrame[] {
  return frames.filter((f) => f.status === 'described' && f.informative !== false && f.has_image);
}

/** The usable frame nearest `seconds` inside the citation window, or null. */
export function nearestFrame(frames: VideoFrame[], seconds: number | null | undefined): VideoFrame | null {
  if (seconds == null || !Number.isFinite(seconds)) return null;
  let best: VideoFrame | null = null;
  let bestDistance = Infinity;
  for (const f of usableFrames(frames)) {
    const delta = f.timestamp_seconds - seconds;
    if (delta < -STILL_WINDOW_BEFORE_S || delta > STILL_WINDOW_AFTER_S) continue;
    const distance = Math.abs(delta);
    if (distance < bestDistance) {
      best = f;
      bestDistance = distance;
    }
  }
  return best;
}
