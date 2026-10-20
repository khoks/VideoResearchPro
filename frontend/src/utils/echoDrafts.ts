/** "Speak as me" (S-3.4.1, S-3.4.2): words for citations, errors and edits. */
import type { DraftCitation, DraftEdit } from '../services/echoApi';

/** What goes on the clipboard: the user's version, and the disclosure line
 * unless they removed it. */
export function withDisclosure(text: string, disclosure: string, keep: boolean): string {
  const body = text.trim();
  return keep && disclosure ? `${body}\n\n${disclosure}` : body;
}

/** After saving: what Echo will learn from, in words. */
export function learnedLine(edit: DraftEdit | null | undefined): string {
  if (!edit) return '';
  const n = edit.written_words;
  if (n === 0) return 'Saved. You used it as drafted, so Echo has nothing new to learn.';
  return `Saved. Echo learns your voice from the ${n === 1 ? 'word' : `${n} words`} you wrote, never from the ones it drafted.`;
}

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
