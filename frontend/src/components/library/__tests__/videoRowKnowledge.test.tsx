/**
 * The library row offers a knowledge report for every source whose text has
 * been read: a PDF, a pasted page and a thread as well as a YouTube video.
 * Before this the library rows had no way in at all, and the job page's
 * button opened nothing for a row without a `video_id`. The drawer is keyed
 * on the document id (D-070), and only a video shows the frames panel.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LibraryVideoResponse } from '../../../services/libraryApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let featureOn = true;
let artifact: Record<string, unknown> | null = null;
const knowledgeIds: string[] = [];
const extractIds: string[] = [];
const mutate = vi.fn();

vi.mock('../../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => featureOn }));
vi.mock('../../notes', () => ({ NotesPanel: () => null }));
vi.mock('../../tags/DocumentTags', () => ({ DocumentTags: () => null }));
vi.mock('../../qa/SuggestionCard', () => ({ SuggestionCard: () => null }));
vi.mock('../../frames/VideoFramesPanel', () => ({
  VideoFramesPanel: ({ videoId }: { videoId: string }) => <div data-testid="frames" data-video={videoId} />,
}));
vi.mock('../../../hooks/useKnowledge', () => ({
  useKnowledge: (id: string) => {
    knowledgeIds.push(id);
    return { data: artifact, isLoading: false, isError: false };
  },
  useExtractKnowledge: (id: string) => {
    extractIds.push(id);
    return { mutate, isPending: false, isSuccess: false, isError: false, data: undefined };
  },
}));

import { VideoRow } from '../VideoRow';

function row(overrides: Partial<LibraryVideoResponse>): LibraryVideoResponse {
  return {
    id: 'doc-1',
    video_id: null,
    title: 'A source',
    channel_id: null,
    channel_name: '',
    url: 'https://example.com/a',
    thumbnail_url: null,
    duration_seconds: null,
    published_at: null,
    source_type: 'article',
    transcript_status: 'fetched',
    transcript_language: 'en',
    transcript_word_count: 1200,
    job_count: 0,
    job_titles: [],
    tags: [],
    ...overrides,
  };
}

const PDF = row({ id: 'doc-pdf-1', title: 'Annual report', source_type: 'pdf', url: '/api/v1/library/pdf/abc.pdf' });
const PAGE = row({ id: 'doc-page-1', title: 'An essay', source_type: 'article' });
const THREAD = row({ id: 'doc-thread-1', title: 'A thread', source_type: 'reddit_post' });
const VIDEO = row({
  id: 'doc-video-1',
  video_id: 'dQw4w9WgXcQ',
  title: 'A talk',
  source_type: 'video',
  url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
  duration_seconds: 600,
});

let host: HTMLDivElement;
let root: Root;

function mount(video: LibraryVideoResponse) {
  act(() =>
    root.render(
      <MemoryRouter>
        <VideoRow video={video} />
      </MemoryRouter>,
    ),
  );
}

const knowledgeButton = () =>
  Array.from(host.querySelectorAll('button')).find((b) => (b.textContent ?? '').trim() === 'Knowledge') as
    | HTMLButtonElement
    | undefined;

const drawer = () => document.body.querySelector('[role="dialog"][aria-label^="Knowledge report for"]');

beforeEach(() => {
  featureOn = true;
  artifact = null;
  knowledgeIds.length = 0;
  extractIds.length = 0;
  mutate.mockReset();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('VideoRow: knowledge report', () => {
  it.each([
    ['an uploaded PDF', PDF],
    ['a pasted page', PAGE],
    ['a thread', THREAD],
  ])('offers it on %s and opens the drawer keyed on the document id', (_label, video) => {
    mount(video);
    const button = knowledgeButton();
    expect(button).toBeTruthy();
    expect(button!.disabled).toBe(false);
    expect(drawer()).toBeNull();

    act(() => button!.click());

    expect(drawer()?.getAttribute('aria-label')).toBe(`Knowledge report for ${video.title}`);
    expect(knowledgeIds).toContain(video.id);
    expect(extractIds).toContain(video.id);
    // Nothing extracted yet: the drawer generates the report on open.
    expect(mutate).toHaveBeenCalledTimes(1);
    // A document with no video stream has no frames panel.
    expect(document.body.querySelector('[data-testid="frames"]')).toBeNull();
  });

  it('offers it on a video too, with the frames panel', () => {
    artifact = { topics: [], concepts: [], events: [], facts: [], knowledge_report_md: '# R' };
    mount(VIDEO);
    act(() => knowledgeButton()!.click());
    expect(drawer()).not.toBeNull();
    expect(mutate).not.toHaveBeenCalled(); // already extracted: shown, not regenerated
    expect(document.body.querySelector('[data-testid="frames"]')?.getAttribute('data-video')).toBe('doc-video-1');
  });

  it('is not offered before the text has been read', () => {
    mount(row({ id: 'doc-pending', source_type: 'pdf', transcript_status: 'pending' }));
    expect(knowledgeButton()).toBeUndefined();
  });

  it('is disabled while the knowledge models are down', () => {
    featureOn = false;
    mount(PDF);
    expect(knowledgeButton()!.disabled).toBe(true);
  });

  it('closes again', () => {
    mount(PDF);
    act(() => knowledgeButton()!.click());
    const close = Array.from(document.body.querySelectorAll('[role="dialog"] button')).find(
      (b) => b.textContent === 'Close',
    ) as HTMLButtonElement;
    act(() => close.click());
    expect(drawer()).toBeNull();
  });
});
