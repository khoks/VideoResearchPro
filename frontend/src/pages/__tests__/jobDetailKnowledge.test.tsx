/**
 * The job page's Knowledge button, at the page itself. Before 2026-10-25 the
 * drawer was gated on `knowledgeVideo.video_id` and keyed on it, so the
 * button on a thread, podcast or PDF row (no `video_id`) opened nothing. It
 * now opens on the document id (D-070) and passes the source type, so only a
 * video shows the frames panel. Restoring either the old gate or the old key
 * fails the first test; dropping `sourceType` fails its frames assertion.
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job } from '../../types/job';
import type { Video } from '../../types/video';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let featureOn = true;
let job: Job;
let videos: Video[] = [];
const knowledgeIds: string[] = [];
const extractIds: string[] = [];
const mutate = vi.fn();

vi.mock('../../hooks/useJobs', () => ({
  useJob: () => ({ data: job, isLoading: false }),
  useJobVideos: () => ({ data: videos }),
  useApproveJob: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
  useCancelJob: () => ({ mutate: vi.fn() }),
  useDeleteJob: () => ({ mutate: vi.fn() }),
}));
vi.mock('../../hooks/useJobProgress', () => ({ useJobProgress: () => undefined }));
vi.mock('../../services/wsClient', () => ({ wsClient: { subscribe: () => () => undefined } }));
vi.mock('../../hooks/useQA', () => ({
  useQAHistory: () => ({ data: [] }),
  useAskQuestion: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAskQuestionStreaming: () => ({ askStreaming: vi.fn(), stage: null, isStreaming: false }),
  useClarifyQuestion: () => ({ mutateAsync: vi.fn(), isPending: false }),
  QAStreamHttpError: class extends Error {},
}));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => featureOn }));
vi.mock('../../hooks/useTierCapabilities', () => ({ useTierCapabilities: () => ({ has: () => false }) }));
vi.mock('../../hooks/useJobTemplates', () => ({ useSaveJobAsTemplate: () => ({ mutateAsync: vi.fn() }) }));
vi.mock('../../hooks/useExchangeFocus', () => ({ useExchangeFocus: () => undefined }));
vi.mock('../../components/templates', () => ({ SaveTemplateModal: () => null }));
vi.mock('../../components/shelves', () => ({ JobShelfChips: () => null, ShelfPicker: () => null }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));
vi.mock('../../components/qa/SuggestionCard', () => ({ SuggestionCard: () => null }));
vi.mock('../../components/qa/Composer', () => ({
  QADock: ({ children }: { children: ReactNode }) => <>{children}</>,
  QAThread: ({ children }: { children: ReactNode }) => <>{children}</>,
  DockedComposer: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock('../../components/frames/VideoFramesPanel', () => ({
  VideoFramesPanel: ({ videoId }: { videoId: string }) => <div data-testid="frames" data-video={videoId} />,
}));
vi.mock('../../hooks/useKnowledge', () => ({
  useKnowledge: (id: string) => {
    knowledgeIds.push(id);
    return { data: null, isLoading: false, isError: false };
  },
  useExtractKnowledge: (id: string) => {
    extractIds.push(id);
    return { mutate, isPending: false, isSuccess: false, isError: false, data: undefined };
  },
}));

import { JobDetailPage } from '../JobDetailPage';

const JOB: Job = {
  id: 'job-1',
  job_type: 'topic',
  status: 'completed',
  created_at: '2026-10-20T10:00:00Z',
  updated_at: '2026-10-20T11:00:00Z',
  completed_at: '2026-10-20T11:00:00Z',
  topic: 'Tidal energy storage',
  search_instructions: null,
  num_videos: 2,
  min_duration_minutes: null,
  max_duration_minutes: null,
  channel_type_filters: null,
  preferred_channels: null,
  channel_list: null,
  videos_per_channel: null,
  output_length: null,
  visual_analysis: false,
  template_id: null,
  template_version: null,
  progress_pct: 100,
  progress_message: 'Done',
  error_message: null,
  video_count: 2,
  transcript_count: 2,
  has_report: false,
};

function source(overrides: Partial<Video>): Video {
  return {
    id: 'row',
    video_id: null,
    document_id: 'doc',
    source_type: 'video',
    source_id: '',
    source_url: null,
    source_metadata: {},
    classification: null,
    title: 'A source',
    channel_name: '',
    channel_id: null,
    url: 'https://example.com/a',
    duration_seconds: null,
    published_at: null,
    thumbnail_url: null,
    approved: true,
    transcript_status: 'fetched',
    transcript_word_count: 900,
    transcript_language: 'en',
    ...overrides,
  };
}

const THREAD = source({
  id: 'row-thread',
  document_id: 'doc-thread-1',
  source_type: 'reddit_post',
  source_id: 'reddit:abc',
  title: 'A thread about tidal storage',
  url: 'https://www.reddit.com/r/energy/comments/abc/',
});
const VIDEO = source({
  id: 'row-video',
  video_id: 'dQw4w9WgXcQ',
  document_id: 'doc-video-1',
  source_type: 'video',
  title: 'A talk on tidal storage',
  url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
  duration_seconds: 600,
});

let host: HTMLDivElement;
let root: Root;

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/jobs/job-1']}>
          <Routes>
            <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
}

/** The Knowledge button on the row whose title link reads `title`. */
function knowledgeButtonFor(title: string): HTMLButtonElement | undefined {
  const link = Array.from(host.querySelectorAll('a')).find((a) => a.textContent === title);
  const row = link?.closest('div')?.parentElement;
  return Array.from(row?.querySelectorAll('button') ?? []).find(
    (b) => (b.textContent ?? '').trim() === 'Knowledge',
  ) as HTMLButtonElement | undefined;
}

const drawer = () => document.body.querySelector('[role="dialog"][aria-label^="Knowledge report for"]');
const frames = () => document.body.querySelector('[data-testid="frames"]');

beforeEach(() => {
  featureOn = true;
  job = JOB;
  videos = [THREAD, VIDEO];
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

describe('JobDetailPage: knowledge report per source', () => {
  it('opens the drawer for a row with no video_id, keyed on its document id, without frames', () => {
    mount();
    const button = knowledgeButtonFor(THREAD.title);
    expect(button).toBeTruthy();
    expect(button!.disabled).toBe(false);
    expect(drawer()).toBeNull();

    act(() => button!.click());

    expect(drawer()?.getAttribute('aria-label')).toBe(`Knowledge report for ${THREAD.title}`);
    expect(knowledgeIds).toContain('doc-thread-1');
    expect(extractIds).toContain('doc-thread-1');
    expect(knowledgeIds).not.toContain('row-thread');
    // Nothing extracted yet: the drawer generates the report on open.
    expect(mutate).toHaveBeenCalledTimes(1);
    // A thread has no video stream, so no frames panel.
    expect(frames()).toBeNull();
  });

  it('opens it for a video row too, with the frames panel', () => {
    mount();
    act(() => knowledgeButtonFor(VIDEO.title)!.click());

    expect(drawer()?.getAttribute('aria-label')).toBe(`Knowledge report for ${VIDEO.title}`);
    expect(knowledgeIds).toContain('doc-video-1');
    expect(frames()?.getAttribute('data-video')).toBe('doc-video-1');
  });

  it('offers no button before a source has been read', () => {
    videos = [{ ...THREAD, transcript_status: 'pending' }];
    mount();
    expect(knowledgeButtonFor(THREAD.title)).toBeUndefined();
  });
});
