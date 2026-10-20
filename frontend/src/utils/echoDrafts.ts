/** "Speak as me" (S-3.4.1): words for citations and API errors. */
import type { DraftCitation } from '../services/echoApi';

export function citationLabel(c: DraftCitation): string {
  switch (c.kind) {
    case 'source':
      return c.label;
    case 'note':
      return 'your note';
    case 'fact':
      return 'what Echo knows about you';
    case 'qa':
      return 'a question you asked before';
    case 'share':
      return c.label || 'something you shared';
    default:
      return c.label || 'your library';
  }
}

export type DraftError =
  | { code: 'names_need_confirmation'; names: string[]; message: string }
  | { code: string; names: string[]; message: string };

/** The API's 409 / 429 detail, or a generic failure. */
export function draftErrorOf(err: unknown): DraftError {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (detail && typeof detail === 'object') {
    const d = detail as { code?: string; message?: string; names?: string[] };
    return { code: d.code ?? 'error', names: d.names ?? [], message: d.message ?? 'Could not draft a reply.' };
  }
  return { code: 'error', names: [], message: typeof detail === 'string' ? detail : 'Could not draft a reply. Try again.' };
}
