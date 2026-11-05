/**
 * T-1.5.13.5: a run's page says which sources it searched. The response has
 * carried `source_types` since S-1.5.13, and the page ignored it, so a run
 * over Reddit and Hacker News read like any other. Checked on the page the
 * router mounts. Removing the row from `JobParamsCard` fails these.
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job } from '../../types/job';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let job: Job;

vi.mock('../../hooks/useJobs', () => ({
  useJob: () => ({ data: job, isLoading: false }),
  useJobVideos: () => ({ data: [] }),
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
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
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
  num_videos: 6,
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
  video_count: 6,
  transcript_count: 6,
  has_report: false,
};

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

function mount(overrides: Partial<Job>) {
  job = { ...JOB, ...overrides };
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

function sourcesRow(): string | null {
  const dt = Array.from(host.querySelectorAll('dt')).find((d) => d.textContent === 'Sources');
  return dt?.nextElementSibling?.textContent ?? null;
}

describe('the sources a run searched', () => {
  it('are named with the words the submit form uses', () => {
    mount({ source_types: ['video', 'reddit_post', 'hn_story'] });
    expect(sourcesRow()).toBe('YouTube, Reddit, Hacker News');
  });

  it('are named for a plain YouTube run too', () => {
    mount({ source_types: ['video'] });
    expect(sourcesRow()).toBe('YouTube');
  });

  it('are named for a channel run', () => {
    mount({ job_type: 'channel', topic: null, channel_list: ['@tides'], source_types: ['video'] });
    expect(sourcesRow()).toBe('YouTube');
  });

  it('read sensibly for a source this build has no label for', () => {
    mount({ source_types: ['video', 'new_source'] });
    expect(sourcesRow()).toBe('YouTube, new source');
  });

  it('show nothing when the response has none', () => {
    mount({ source_types: undefined });
    expect(sourcesRow()).toBeNull();
    mount({ source_types: [] });
    expect(sourcesRow()).toBeNull();
  });
});
