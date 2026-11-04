// A document's measured language mix in words, for the badge beside
// `transcript_language` (T-1.16.1.9).
//
// `transcript_language` is the caption track's label, which calls romanised
// Hinglish `en`. `language_mix` (T-1.16.1.7) is measured from the words, so
// it is the one that can say "Hindi + English". The names follow the
// backend's own wording for prompts (`code_mixing_service.source_note`):
// Hindi in Devanagari or romanised, Urdu/Hindi in Arabic script, any other
// script by its name.
import type { LanguageMix } from '../types/video';

const LANGUAGE_BY_SCRIPT: Record<string, string> = {
  Devanagari: 'Hindi',
  Latin: 'Hindi',
  Arabic: 'Urdu/Hindi',
};

/** At or above this share of non-English words a source reads as that
 * language alone; `source_note` uses the same cut. */
export const SOLE_LANGUAGE_SHARE = 0.95;

export interface LanguageMixBadge {
  /** "Hindi + English", "English + Hindi", "Hindi (romanised) + English", "Hindi"… */
  label: string;
  /** One sentence for the tooltip: the measured shares. */
  description: string;
}

function languageName(primary: string, script: string): string {
  if (primary === 'other' || (script && !(script in LANGUAGE_BY_SCRIPT))) {
    return script ? `${script} script` : 'Non-English';
  }
  const name = LANGUAGE_BY_SCRIPT[script] ?? 'Hindi';
  return script === 'Latin' ? `${name} (romanised)` : name;
}

function percent(share: number): string {
  return `${Math.round(Math.max(0, Math.min(1, share)) * 100)}%`;
}

/**
 * The badge for a document's language mix, or null when it gets none.
 *
 * Only a document that is not plain English gets one, and the profile says
 * which those are: `code_mixed` is the chunker's own 3% rule applied to the
 * measured text. A missing profile (not yet chunked or backfilled), plain
 * English and a text with no language-bearing words (`none`) show nothing.
 */
export function languageMixBadge(mix: LanguageMix | null | undefined): LanguageMixBadge | null {
  if (!mix || !mix.code_mixed) return null;
  const primary = mix.primary_language;
  if (primary !== 'en' && primary !== 'hi' && primary !== 'other') return null;
  const script = mix.native_script ?? '';
  const lang = languageName(primary, script);
  const share = Number.isFinite(mix.hi_share) ? mix.hi_share : 0;
  const matrix = Number.isFinite(mix.matrix_hi_share) ? mix.matrix_hi_share : 0;

  let label: string;
  if (primary === 'en') label = `English + ${lang}`;
  else if (share >= SOLE_LANGUAGE_SHARE) label = lang;
  else label = `${lang} + English`;

  const short = lang.split(' (')[0];
  const description =
    `Measured from the words: ${percent(share)} ${short}, ` +
    `${short} grammar in ${percent(matrix)} of the speech.`;
  return { label, description };
}
