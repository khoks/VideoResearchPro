// A document's measured language mix in words, for the badge beside
// `transcript_language` (T-1.16.1.9).
//
// `transcript_language` is the source's label, which calls romanised Hinglish
// `en`. `language_mix` (T-1.16.1.7) is measured from the words, so it is the
// one that can say "Hindi + English". Until T-1.16.2.15 the tagger knew two
// classes, and conversational Spanish or Turkish measured `primary_language:
// hi`. It now abstains on Latin text with no Hindi evidence and reports
// `other`, which this file trusts, as it does a low `named_share` on an English
// source. A profile stored before that still says `hi`, so on Latin-script text
// `hi` alone proves "not English", never "Hindi".
//
// So the badge names Hindi only where something else supports it:
// - a label naming a third language (`es`, `kn`, Whisper's `spanish`) wins;
// - Devanagari is Hindi, and so is Latin or Arabic script labelled hi or ur;
// - a YouTube caption track labelled `en` with non-English grammar in the
//   words is the romanised Hinglish this badge exists for. Only a video's
//   label is evidence: PDFs, Reddit and HN are `en` by assumption.
// Anything else stays neutral. Other scripts go by their name.
import type { LanguageMix } from '../types/video';

/** At or above this share of non-English words a source reads as that
 * language alone; `source_note` uses the same cut. */
export const SOLE_LANGUAGE_SHARE = 0.95;

/** The least Hindi-grammar share that counts as a Hindi signal on a video
 * captioned `en`. English talks read 0 to 0.4%, even ones full of Indian
 * proper names (Krishna, Aamir Khan), measured on 219 cached transcripts on
 * 2026-11-04. */
export const HINDI_GRAMMAR_FLOOR = 0.05;

/** Below this share of its non-English words named, the tagger abstained on the
 * source (`NAMED_MIN_SHARE` in `code_mixing_service`). */
export const NAMED_MIN_SHARE = 0.5;

/** Non-English grammar below this means English frames most of the speech
 * (`ENGLISH_FRAMED_BELOW`, the same cut `source_note` uses). */
export const ENGLISH_FRAMED_BELOW = 0.5;

/** Labels that name no language. */
const NOT_A_LANGUAGE = new Set(['unknown', 'und', 'mul', 'mis', 'zxx']);

/** Captions carry a BCP-47 code, Whisper writes the language's English name,
 * and some sources carry an ISO 639-2 code (T-1.16.1.10). */
const CODE_BY_NAME: Record<string, string> = {
  english: 'en', hindi: 'hi', urdu: 'ur',
  eng: 'en', hin: 'hi', urd: 'ur',
};

export interface LanguageMixBadge {
  /** "Hindi + English", "Hindi (romanised) + English", "Spanish", "English + other words"… */
  label: string;
  /** One sentence for the tooltip: the measured shares. */
  description: string;
}

function languageCode(label: string | null | undefined): string {
  const base = (label ?? '').trim().toLowerCase().split(/[-_]/)[0];
  return CODE_BY_NAME[base] ?? base;
}

/** The language a label names when it is neither English nor Hindi/Urdu. */
function thirdLanguage(code: string): string | null {
  if (!code || code === 'en' || code === 'hi' || code === 'ur' || NOT_A_LANGUAGE.has(code)) return null;
  if (/^[a-z ]{4,}$/.test(code)) return code[0].toUpperCase() + code.slice(1);
  try {
    return new Intl.DisplayNames(['en'], { type: 'language', fallback: 'none' }).of(code) ?? null;
  } catch {
    return null;
  }
}

type Evidence = 'hindi' | 'other' | 'unnamed';

/** What the script, the label and the words together support calling it. */
function nameFromWords(
  mix: LanguageMix,
  matrix: number,
  code: string,
  sourceType: string | undefined,
): { name: string; evidence: Evidence } {
  const script = mix.native_script ?? '';
  const labelledHindi = code === 'hi' || code === 'ur';
  if (script === 'Devanagari') return { name: 'Hindi', evidence: 'hindi' };
  if (script === 'Arabic') {
    return labelledHindi ? { name: 'Urdu/Hindi', evidence: 'hindi' } : { name: 'Arabic script', evidence: 'other' };
  }
  if (script === 'Latin') {
    // The tagger abstaining: an `en` label cannot make that Hindi.
    const abstained = mix.primary_language === 'other' || (mix.named_share ?? 1) < NAMED_MIN_SHARE;
    const hinglishCaptions = !abstained && sourceType === 'video' && code === 'en'
      && matrix >= HINDI_GRAMMAR_FLOOR;
    if (labelledHindi || hinglishCaptions) return { name: 'Hindi (romanised)', evidence: 'hindi' };
    return { name: mix.primary_language === 'en' ? 'other words' : 'Other language', evidence: 'unnamed' };
  }
  return { name: script ? `${script} script` : 'Non-English', evidence: 'other' };
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
 * The label and the source type only decide what the mix may be called.
 *
 * @param language the row's `transcript_language`
 * @param sourceType the row's source type
 */
export function languageMixBadge(
  mix: LanguageMix | null | undefined,
  language?: string | null,
  sourceType?: string,
): LanguageMixBadge | null {
  if (!mix || !mix.code_mixed) return null;
  const primary = mix.primary_language;
  if (primary !== 'en' && primary !== 'hi' && primary !== 'other') return null;
  const share = Number.isFinite(mix.hi_share) ? mix.hi_share : 0;
  const matrix = Number.isFinite(mix.matrix_hi_share) ? mix.matrix_hi_share : 0;
  const code = languageCode(language);
  const third = thirdLanguage(code);

  // A third language in Latin letters: the shares only mean "not in the
  // English lexicon", so there is no mix to report.
  if (third && (!mix.native_script || mix.native_script === 'Latin')) {
    return {
      label: third,
      description: `Labelled ${third}. The word measure only tells English from Hindi, so it has no shares for this source.`,
    };
  }

  const { name, evidence } = third
    ? { name: third, evidence: 'other' as Evidence }
    : nameFromWords(mix, matrix, code, sourceType);

  // An abstained source's "English" words are homographs of its own (`a`,
  // `no`), so the measure says nothing about a mix with English, unless
  // English frames most of the speech: then it is a bilingual source.
  const noEnglish = primary === 'other' && evidence === 'unnamed' && matrix >= ENGLISH_FRAMED_BELOW;

  let label: string;
  if (primary === 'en') label = `English + ${name}`;
  else if (share >= SOLE_LANGUAGE_SHARE || noEnglish) label = name;
  else label = `${name} + English`;

  const short = name.split(' (')[0];
  let description: string;
  if (evidence === 'hindi') {
    description = `Measured from the words: ${percent(share)} ${short}, ${short} grammar in ${percent(matrix)} of the speech.`;
  } else if (evidence === 'other') {
    description = `Measured from the words: ${percent(share)} ${short}.`;
  } else {
    description = `Measured from the words: ${percent(share)} are outside the English word list. Nothing says which language they are.`;
  }
  return { label, description };
}
