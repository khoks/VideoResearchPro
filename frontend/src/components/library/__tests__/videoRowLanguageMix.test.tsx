/**
 * T-1.16.1.9: a library row shows the document's measured language mix
 * (`documents.language_mix`, T-1.16.1.7) as a badge beside the caption
 * track's `transcript_language`, which calls romanised Hinglish `en`.
 * Only a source that is not plain English gets one; the profile's
 * `code_mixed` (the chunker's 3% rule) says which.
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
import { languageMixBadge } from '../../../utils/languageMix';

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

describe('languageMixBadge', () => {
  it('names the mix the way the backend names it for prompts', () => {
    expect(languageMixBadge(ROMANISED)?.label).toBe('Hindi (romanised) + English');
    expect(languageMixBadge(DEVANAGARI)?.label).toBe('Hindi + English');
    expect(languageMixBadge(ALL_HINDI)?.label).toBe('Hindi');
    expect(languageMixBadge(MOSTLY_ENGLISH)?.label).toBe('English + Hindi');
    expect(languageMixBadge(BENGALI)?.label).toBe('Bengali script + English');
    expect(languageMixBadge(mix({ ...DEVANAGARI, native_script: 'Arabic' }))?.label).toBe('Urdu/Hindi + English');
  });

  it('gives plain English, an unprofiled document and a wordless one no badge', () => {
    expect(languageMixBadge(PLAIN_ENGLISH)).toBeNull();
    expect(languageMixBadge(null)).toBeNull();
    expect(languageMixBadge(undefined)).toBeNull();
    expect(languageMixBadge(mix({ primary_language: 'none', code_mixed: true }))).toBeNull();
  });

  it('follows code_mixed, not the shares, to decide (the chunker’s rule lives on the server)', () => {
    // A small share the server still calls mixed (its quote mode is not plain English).
    expect(languageMixBadge(mix({ native_script: 'Latin', hi_share: 0.01, quote_mode: 'roman', code_mixed: true }))?.label)
      .toBe('English + Hindi (romanised)');
    // A share above 3% the server did not flag is left alone.
    expect(languageMixBadge(mix({ native_script: 'Latin', hi_share: 0.05, code_mixed: false }))).toBeNull();
  });

  it('describes the measured shares for the tooltip', () => {
    expect(languageMixBadge(ROMANISED)?.description).toBe(
      'Measured from the words: 62% Hindi, Hindi grammar in 81% of the speech.',
    );
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
    ]);

    expect(badgesOf('hinglish-talk')).toEqual(['Hindi (romanised) + English']);
    expect(badgesOf('english-page')).toEqual([]);
    expect(badgesOf('unprofiled-page')).toEqual([]);
    expect(badgesOf('older-response')).toEqual([]);

    const wrapper = host.querySelector('[data-testid="language-mix"]')!;
    expect(wrapper.getAttribute('title')).toBe('Measured from the words: 62% Hindi, Hindi grammar in 81% of the speech.');
    // Beside the caption label: the badge right after it.
    const caption = wrapper.previousElementSibling;
    expect(caption?.textContent).toBe('en');
    expect(host.querySelectorAll('[data-testid="language-mix"]')).toHaveLength(1);
  });
});
