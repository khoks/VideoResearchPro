/** The YouTube video id of a citation, from its explicit `video_id` or its
 * URL (`watch?v=`, `youtu.be/`, `/shorts/`). Null for anything else. */
export function youtubeVideoId(ref: { video_id?: string | null; youtube_link?: string; video_url?: string }): string | null {
  if (ref.video_id) return ref.video_id;
  for (const raw of [ref.youtube_link, ref.video_url]) {
    if (!raw) continue;
    let url: URL;
    try {
      url = new URL(raw);
    } catch {
      continue;
    }
    const host = url.hostname.replace(/^www\.|^m\./, '');
    if (host === 'youtu.be') {
      const id = url.pathname.split('/')[1];
      if (id) return id;
    }
    if (host === 'youtube.com' || host.endsWith('.youtube.com')) {
      const v = url.searchParams.get('v');
      if (v) return v;
      const shorts = url.pathname.match(/^\/(?:shorts|live)\/([^/?#]+)/);
      if (shorts) return shorts[1];
    }
  }
  return null;
}
