/**
 * T-1.16.1.9: a library row shows the document's measured language mix
 * (`documents.language_mix`, T-1.16.1.7) as a badge beside the caption
 * track's `transcript_language`, which calls romanised Hinglish `en`.
 * Only a source that is not plain English gets one; the profile's
 * `code_mixed` (the chunker's 3% rule) says which. The profile cannot say
 * what a Latin-script source IS: the tagger counts every word outside its
 * English lexicon as `hi`, so Hindi is named only where something supports it.
 *
 * Rendered through `DocumentsBrowser`, the list the channel and shelf pages
 * use, fed rows shaped like `GET /library/videos`.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LibraryVideoResponse } from '../../../services/libraryApi';
import type { LanguageMix } from '../../../types/video';
import { HINDI_GRAMMAR_FLOOR, languageMixBadge } from '../../../utils/languageMix';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('../../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../notes', () => ({ NotesPanel: () => null }));
vi.mock('../../tags/DocumentTags', () => ({ DocumentTags: () => null }));

import { DocumentsBrowser } from '../DocumentsBrowser';

function mix(overrides: Partial<LanguageMix>): LanguageMix {
  return {
    primary_language: 'en',
    native_script: null,
    hi_share: 0,
    matrix_hi_share: 0,
    quote_mode: 'plain_english',
    code_mixed: false,
    ...overrides,
  };
}

// Profiles as `language_mix_service.public_view` serves them.
const PLAIN_ENGLISH = mix({});
const ROMANISED = mix({
  primary_language: 'hi', native_script: 'Latin', hi_share: 0.62, matrix_hi_share: 0.81,
  quote_mode: 'roman', code_mixed: true,
});
const DEVANAGARI = mix({
  primary_language: 'hi', native_script: 'Devanagari', hi_share: 0.41, matrix_hi_share: 0.7,
  quote_mode: 'native_script', code_mixed: true,
});
const ALL_HINDI = mix({
  primary_language: 'hi', native_script: 'Devanagari', hi_share: 0.97, matrix_hi_share: 1,
  quote_mode: 'native_script', code_mixed: true,
});
const MOSTLY_ENGLISH = mix({
  primary_language: 'en', native_script: 'Devanagari', hi_share: 0.08, matrix_hi_share: 0.1,
  quote_mode: 'roman', code_mixed: true,
});
const BENGALI = mix({
  primary_language: 'other', native_script: 'Bengali', hi_share: 0.7, matrix_hi_share: 0.9,
  quote_mode: 'native_script', code_mixed: true,
});
// As `code_mixing_service.profile_transcript` measures these texts.
const SPANISH_ESSAY = mix({
  primary_language: 'en', native_script: 'Latin', hi_share: 0.2264, matrix_hi_share: 0,
  quote_mode: 'roman', code_mixed: true,
});
const SPANISH_SPEECH = mix({
  primary_language: 'hi', native_script: 'Latin', hi_share: 0.5494, matrix_hi_share: 0.598,
  quote_mode: 'roman', code_mixed: true,
});
const ARABIC = mix({
  primary_language: 'hi', native_script: 'Arabic', hi_share: 1, matrix_hi_share: 1,
  quote_mode: 'native_script', code_mixed: true,
});
const KANNADA = mix({
  primary_language: 'other', native_script: 'Kannada', hi_share: 1, matrix_hi_share: 1,
  quote_mode: 'native_script', code_mixed: true,
});
// A real English talk from the library: 3% of its words are proper names.
const ENGLISH_WITH_NAMES = mix({
  primary_language: 'en', native_script: 'Latin', hi_share: 0.0333, matrix_hi_share: 0.0037,
  quote_mode: 'plain_english', code_mixed: true,
});

describe('languageMixBadge', () => {
  it('names the mix the way the backend names it for prompts', () => {
    expect(languageMixBadge(ROMANISED, 'en', 'video')?.label).toBe('Hindi (romanised) + English');
    expect(languageMixBadge(DEVANAGARI, 'hi', 'video')?.label).toBe('Hindi + English');
    expect(languageMixBadge(ALL_HINDI, 'hi', 'video')?.label).toBe('Hindi');
    expect(languageMixBadge(MOSTLY_ENGLISH, 'en', 'video')?.label).toBe('English + Hindi');
    expect(languageMixBadge(BENGALI)?.label).toBe('Bengali script + English');
    expect(languageMixBadge(mix({ ...DEVANAGARI, native_script: 'Arabic' }), 'ur', 'video')?.label).toBe(
      'Urdu/Hindi + English',
    );
  });

  it('gives plain English, an unprofiled document and a wordless one no badge', () => {
    expect(languageMixBadge(PLAIN_ENGLISH)).toBeNull();
    expect(languageMixBadge(null)).toBeNull();
    expect(languageMixBadge(undefined)).toBeNull();
    expect(languageMixBadge(mix({ primary_language: 'none', code_mixed: true }))).toBeNull();
  });

  it('follows code_mixed, not the shares, to decide (the chunker’s rule lives on the server)', () => {
    // A small share the server still calls mixed (its quote mode is not plain English).
    expect(languageMixBadge(mix({ native_script: 'Devanagari', hi_share: 0.01, quote_mode: 'roman', code_mixed: true }))?.label)
      .toBe('English + Hindi');
    // A share above 3% the server did not flag is left alone.
    expect(languageMixBadge(mix({ native_script: 'Latin', hi_share: 0.05, code_mixed: false }), 'hi', 'video')).toBeNull();
  });

  it('describes the measured shares for the tooltip', () => {
    expect(languageMixBadge(ROMANISED, 'en', 'video')?.description).toBe(
      'Measured from the words: 62% Hindi, Hindi grammar in 81% of the speech.',
    );
    expect(languageMixBadge(BENGALI)?.description).toBe('Measured from the words: 70% Bengali script.');
  });
});

describe('languageMixBadge names Hindi only where something supports it', () => {
  it('shows the third language a label names, with no shares for it', () => {
    expect(languageMixBadge(SPANISH_ESSAY, 'es', 'video')?.label).toBe('Spanish');
    expect(languageMixBadge(SPANISH_SPEECH, 'es-419', 'video')?.label).toBe('Spanish');
    // Whisper writes the language's name, not its code.
    expect(languageMixBadge(SPANISH_SPEECH, 'spanish', 'video')?.label).toBe('Spanish');
    expect(languageMixBadge(SPANISH_ESSAY, 'welsh', 'video')?.label).toBe('Welsh');

    const description = languageMixBadge(SPANISH_SPEECH, 'es', 'video')!.description;
    expect(description).toBe('Labelled Spanish. The word measure only tells English from Hindi, so it has no shares for this source.');
    expect(description).not.toMatch(/\d+%/);
  });

  it('keeps the measured shares under the labelled name in a script of its own', () => {
    expect(languageMixBadge(KANNADA, 'kn', 'video')?.label).toBe('Kannada');
    const tamil = mix({ ...BENGALI, native_script: 'Tamil' });
    expect(languageMixBadge(tamil, 'ta', 'video')?.label).toBe('Tamil + English');
    expect(languageMixBadge(DEVANAGARI, 'mr', 'video')?.label).toBe('Marathi + English');
    expect(languageMixBadge(tamil, 'ta', 'video')?.description).toBe('Measured from the words: 70% Tamil.');
  });

  it('calls Arabic script Urdu/Hindi only when the label does', () => {
    expect(languageMixBadge(ARABIC, 'ar', 'video')?.label).toBe('Arabic');
    expect(languageMixBadge(ARABIC, 'fa', 'video')?.label).toBe('Persian');
    expect(languageMixBadge(ARABIC, null, 'article')?.label).toBe('Arabic script');
    expect(languageMixBadge(ARABIC, 'en', 'pdf')?.label).toBe('Arabic script');
    expect(languageMixBadge(ARABIC, 'ur', 'video')?.label).toBe('Urdu/Hindi');
    expect(languageMixBadge(ARABIC, 'urdu', 'video')?.label).toBe('Urdu/Hindi');
    expect(languageMixBadge(ARABIC, 'hi', 'video')?.label).toBe('Urdu/Hindi');
  });

  it('reads an `en` label as evidence only on a video', () => {
    // The case the badge exists for: captions labelled `en`, words that are not.
    expect(languageMixBadge(ROMANISED, 'en', 'video')?.label).toBe('Hindi (romanised) + English');
    expect(languageMixBadge(ROMANISED, 'en-IN', 'video')?.label).toBe('Hindi (romanised) + English');
    expect(languageMixBadge(ROMANISED, 'english', 'video')?.label).toBe('Hindi (romanised) + English');
    // A PDF, a Reddit thread and an HN post are `en` by assumption, and
    // conversational Spanish measures Hindi grammar in 60% of its speech.
    expect(languageMixBadge(SPANISH_SPEECH, 'en', 'pdf')?.label).toBe('Other language + English');
    expect(languageMixBadge(SPANISH_SPEECH, 'en', 'reddit_thread')?.label).toBe('Other language + English');
    expect(languageMixBadge(mix({ ...SPANISH_SPEECH, hi_share: 0.96 }), 'en', 'pdf')?.label).toBe('Other language');
  });

  it('takes a hi or ur label over the source type', () => {
    expect(languageMixBadge(ROMANISED, 'hi', 'reddit_thread')?.label).toBe('Hindi (romanised) + English');
    expect(languageMixBadge(ENGLISH_WITH_NAMES, 'hi', 'video')?.label).toBe('English + Hindi (romanised)');
  });

  it('does not call the proper names in an English talk Hindi', () => {
    expect(languageMixBadge(ENGLISH_WITH_NAMES, 'en-US', 'video')?.label).toBe('English + other words');
    expect(languageMixBadge(SPANISH_ESSAY, 'en', 'video')?.label).toBe('English + other words');
    const atFloor = mix({ ...ENGLISH_WITH_NAMES, matrix_hi_share: HINDI_GRAMMAR_FLOOR });
    expect(languageMixBadge(atFloor, 'en', 'video')?.label).toBe('English + Hindi (romanised)');
    const below = mix({ ...ENGLISH_WITH_NAMES, matrix_hi_share: HINDI_GRAMMAR_FLOOR - 0.001 });
    expect(languageMixBadge(below, 'en', 'video')?.label).toBe('English + other words');
  });

  it('claims no language in the tooltip of a neutral badge', () => {
    expect(languageMixBadge(ENGLISH_WITH_NAMES, 'en-US', 'video')?.description).toBe(
      'Measured from the words: 3% are outside the English word list. Nothing says which language they are.',
    );
  });

  it.each(['unknown', 'und', 'a.en', '', null, undefined])('falls back on the words for the label %s', (label) => {
    expect(languageMixBadge(DEVANAGARI, label, 'video')?.label).toBe('Hindi + English');
    expect(languageMixBadge(ROMANISED, label, 'video')?.label).toBe('Other language + English');
  });

  // T-1.16.1.10: an ISO 639-2 label names the same language as its two-letter
  // code. Unmapped, `eng` reads as a third language, and Intl then calls it
  // "English" with no shares at all.
  it.each([
    ['eng', 'en'], ['ENG', 'en'], ['hin', 'hi'], ['urd', 'ur'], ['hin-IN', 'hi'],
  ])('reads the ISO 639-2 label %s as %s', (label, code) => {
    for (const profile of [DEVANAGARI, ROMANISED, MOSTLY_ENGLISH, ARABIC]) {
      expect(languageMixBadge(profile, label, 'video')).toEqual(languageMixBadge(profile, code, 'video'));
    }
  });

  it('calls a mixed source labelled eng what it measures, not "English"', () => {
    expect(languageMixBadge(ROMANISED, 'eng', 'video')?.label).toBe('Hindi (romanised) + English');
    expect(languageMixBadge(ROMANISED, 'hin', 'pdf')?.label).toBe('Hindi (romanised) + English');
    expect(languageMixBadge(ARABIC, 'urd', 'video')?.label).toBe('Urdu/Hindi');
  });
});

function row(id: string, overrides: Partial<LibraryVideoResponse>): LibraryVideoResponse {
  return {
    id,
    video_id: null,
    title: id,
    channel_id: null,
    channel_name: '',
    url: `https://example.com/${id}`,
    thumbnail_url: null,
    duration_seconds: null,
    published_at: null,
    source_type: 'article',
    transcript_status: 'fetched',
    transcript_language: 'en',
    transcript_word_count: 900,
    job_count: 1,
    job_titles: ['A run'],
    tags: [],
    ...overrides,
  };
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function mountList(rows: LibraryVideoResponse[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <DocumentsBrowser
            queryKey={['test-docs']}
            fetch={async () => rows}
            emptyTitle="Nothing"
            emptyDescription="Nothing here"
          />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  for (let i = 0; i < 4; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

function badgesOf(title: string): string[] {
  const titleEl = [...host.querySelectorAll('div[title]')].find((el) => el.getAttribute('title') === title);
  const card = titleEl?.parentElement;
  if (!card) throw new Error(`no row titled ${title}`);
  return [...card.querySelectorAll('span')]
    .filter((s) => s.parentElement?.dataset.testid === 'language-mix')
    .map((s) => s.textContent ?? '');
}

describe('VideoRow language badge', () => {
  it('shows the measured mix beside the caption label, only on sources that are not plain English', async () => {
    await mountList([
      // The caption track says `en`; the words say otherwise.
      row('hinglish-talk', { source_type: 'video', video_id: 'mix000abcXY', language_mix: ROMANISED }),
      row('english-page', { language_mix: PLAIN_ENGLISH }),
      row('unprofiled-page', { language_mix: null }),
      row('older-response', {}),
      row('spanish-talk', { source_type: 'video', video_id: 'esp000abcXY', transcript_language: 'es', language_mix: SPANISH_SPEECH }),
      row('spanish-pdf', { source_type: 'pdf', language_mix: SPANISH_SPEECH }),
    ]);

    expect(badgesOf('hinglish-talk')).toEqual(['Hindi (romanised) + English']);
    expect(badgesOf('spanish-talk')).toEqual(['Spanish']);
    expect(badgesOf('spanish-pdf')).toEqual(['Other language + English']);
    expect(badgesOf('english-page')).toEqual([]);
    expect(badgesOf('unprofiled-page')).toEqual([]);
    expect(badgesOf('older-response')).toEqual([]);

    const wrapper = host.querySelectorAll('[data-testid="language-mix"]')[0];
    expect(wrapper.getAttribute('title')).toBe('Measured from the words: 62% Hindi, Hindi grammar in 81% of the speech.');
    // Beside the caption label: the badge right after it.
    const caption = wrapper.previousElementSibling;
    expect(caption?.textContent).toBe('en');
    expect(host.querySelectorAll('[data-testid="language-mix"]')).toHaveLength(3);
  });
});
