/*
 * Pure logic for Echo's shares inbox and quick-share (S-3.7.1). No React.
 *
 * The backend decides the stored content type; these helpers only decide
 * what the quick-share box is about to send and how a share reads in the
 * inbox.
 */

export type QuickShareInput =
  | { kind: 'empty' }
  | { kind: 'url'; url: string }
  | { kind: 'text'; text: string };

/**
 * One box, two meanings: a single http(s) link becomes a link share;
 * anything else (several lines, a quote, a link with commentary) is text.
 * A link with commentary should be split by the user into link plus "why",
 * and the box says so; guessing would lose their words.
 */
export function parseQuickShareInput(raw: string): QuickShareInput {
  const trimmed = raw.trim();
  if (!trimmed) return { kind: 'empty' };
  if (!/\s/.test(trimmed) && /^https?:\/\/[^\s/$.?#].[^\s]*$/i.test(trimmed)) {
    try {
      const u = new URL(trimmed);
      if (u.protocol === 'http:' || u.protocol === 'https:') return { kind: 'url', url: trimmed };
    } catch {
      /* not a URL; treat as text */
    }
  }
  return { kind: 'text', text: raw };
}

const CONTENT_TYPE_LABELS: Record<string, string> = {
  youtube_video: 'YouTube video',
  youtube_short: 'YouTube Short',
  instagram_reel: 'Instagram reel',
  instagram_post: 'Instagram post',
  tiktok_video: 'TikTok video',
  tweet: 'Post on X',
  reddit_post: 'Reddit post',
  link: 'Link',
  bookmark: 'Bookmark',
  text_snippet: 'Text',
  book_quote: 'Quote',
  image: 'Image',
  voice_memo: 'Voice memo',
  video_clip: 'Video clip',
  pdf: 'PDF',
  archive: 'Archive',
  text_file: 'Text file',
  file: 'File',
};

/** The fields of a share's processing record that say how a file was read. */
export interface ShareReading {
  extractor?: string | null;
  language?: string | null;
  duration_seconds?: number | null;
  page_count?: number | null;
  pages_with_text?: number | null;
}

function clock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}

/**
 * How a processed file was read (S-3.7.2), in words. Local OCR and a vision
 * model are named apart because only one of them sends the image out.
 * Null for links, text and text files, whose reading needs no comment.
 */
export function shareReadingLabel(p: ShareReading | null | undefined): string | null {
  switch (p?.extractor) {
    case 'ocr_local':
      return 'Text read by local OCR';
    case 'ocr_vision':
      return 'Text read by a vision model';
    case 'whisper': {
      const parts = ['Transcribed by Whisper'];
      if (p.duration_seconds) parts.push(clock(p.duration_seconds));
      if (p.language && p.language !== 'unknown') {
        parts.push(p.language.charAt(0).toUpperCase() + p.language.slice(1));
      }
      return parts.join(' · ');
    }
    case 'pdf_text': {
      const pages = p.page_count ?? 0;
      if (!pages) return 'Text from the PDF';
      const withText = p.pages_with_text ?? pages;
      if (withText < pages) return `Text from ${withText} of ${pages} pages`;
      return `Text from ${pages} ${pages === 1 ? 'page' : 'pages'}`;
    }
    default:
      return null;
  }
}

export function contentTypeLabel(type: string): string {
  if (CONTENT_TYPE_LABELS[type]) return CONTENT_TYPE_LABELS[type];
  const words = type.replace(/_/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Share';
}

/** Content types the inbox offers when the user corrects one. Free text is
 * also accepted by the backend; these are the common ones. */
export const COMMON_CONTENT_TYPES: string[] = [
  'link',
  'bookmark',
  'youtube_video',
  'text_snippet',
  'book_quote',
  'image',
  'voice_memo',
  'whatsapp_thread',
  'keep_note',
  'own_post',
];

const CONTENT_TYPE_RE = /^[a-z][a-z0-9_]{0,63}$/;

export function isValidContentType(value: string): boolean {
  return CONTENT_TYPE_RE.test(value);
}

export function processingStateLabel(state: string): string {
  switch (state) {
    case 'pending':
      return 'Waiting for processing';
    case 'processed':
      return 'Processed';
    case 'skipped':
      return 'Skipped';
    case 'failed':
      return 'Processing failed';
    default:
      return state;
  }
}

export function authorshipLabel(authorIsTenant: boolean): { label: string; hint: string } {
  return authorIsTenant
    ? {
        label: 'Your words',
        hint: 'You said you wrote this. Echo can learn your voice from it.',
      }
    : {
        label: 'Context only',
        hint: "Someone else's words. Echo can use them as context, but never quotes them and never puts them in a dataset export.",
      };
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Sum of every count in a footprint, for "N items will be deleted". */
export function footprintTotal(fp: { rows: Record<string, number>; files: number; vectors: Record<string, number> }): number {
  const sum = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);
  return sum(fp.rows) + fp.files + sum(fp.vectors);
}

export function isFootprintEmpty(fp: { rows: Record<string, number>; files: number; vectors: Record<string, number> }): boolean {
  return footprintTotal(fp) === 0;
}
