/**
 * T-3.4.1.26: the run page says a failed first read in place of the run, once,
 * under the app's own query client, with the real `useJob` (only the HTTP layer
 * is replaced).
 *
 * A 404 is the run being gone: "We can't find that job." Anything else is
 * "Couldn't load this run." with the server's words, else the page's sentence,
 * and a 401 says nothing (the session ends in one place). The toast stands
 * aside for that first read (`{ inlineErrors: 'load' }`). A poll that fails
 * behind a run already on screen shows no line, so it keeps its toast.
 *
 * Mutation checks, run on 2026-11-10: dropping `{ inlineErrors: 'load' }` fails
 * every row with a line (a toast beside it); `{ inlineErrors: true }` fails "a
 * poll that fails behind the run"; "We can't find that job." for every failure
 * fails the `words`, `noWords` and `noAnswer` rows; and the page without its
 * 401 check fails the `sessionEnded` row with the not-found sentence.
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AxiosError, AxiosHeaders } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job } from '../../types/job';
import { createQueryClient } from '../../services/queryClient';
import {
  FAILURE_KINDS,
  SERVER_WORDS,
  clearToasts,
  failures,
  flush,
  toastMessages,
} from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getJob = vi.fn<(id: string) => Promise<Job>>();
vi.mock('../../services/jobsApi', () => ({
  jobsApi: {
    get: (id: string) => getJob(id),
    getVideos: async () => [],
  },
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

function notFound(): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError('Request failed with status code 404', 'ERR_BAD_REQUEST', undefined, undefined, {
    status: 404, statusText: '404', headers, config: { headers }, data: { detail: 'Job not found' },
  });
}

let host: HTMLDivElement;
let root: Root;

async function mount(client: QueryClient = createQueryClient()) {
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/jobs/job-1']}>
          <Routes>
            <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

/** Moves the clock on by `ms`, then lets what that started settle. */
async function advance(ms: number) {
  await flush();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  await flush();
}

const text = () => host.textContent ?? '';
const count = (needle: string) => text().split(needle).length - 1;

const GONE = "We can't find that job.";
const FAILED = "Couldn't load this run.";
const FALLBACK = 'Something blocked the request. Try again in a moment.';

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  getJob.mockReset();
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

describe('the run page, when its first read fails', () => {
  it('says a 404 once, as the run being gone', async () => {
    getJob.mockRejectedValue(notFound());
    await mount();
    await advance(1000);
    expect(toastMessages()).toEqual([]);
    expect(count(GONE)).toBe(1);
    expect(text()).not.toContain(FAILED);
    expect(text()).not.toContain('Job not found');
  });

  it.each(FAILURE_KINDS)('says any other failure once, with the server’s words or its own (%s)', async (kind) => {
    getJob.mockRejectedValue(failures[kind]());
    await mount();
    await advance(1000);
    expect(toastMessages()).toEqual([]);
    expect(text()).not.toMatch(/Network Error|status code 500|Not authenticated/);
    if (kind === 'sessionEnded') {
      // The session ends in one place; the page says nothing of it.
      expect(text()).not.toContain(FAILED);
      expect(text()).not.toContain(GONE);
      return;
    }
    expect(count(FAILED)).toBe(1);
    expect(count(kind === 'words' ? SERVER_WORDS : FALLBACK)).toBe(1);
    expect(text()).not.toContain(GONE);
  });

  it('says it once across the polls that follow', async () => {
    getJob.mockRejectedValue(failures.noWords());
    await mount();
    await advance(1000);
    await advance(12_000);
    expect(toastMessages()).toEqual([]);
    expect(count(FALLBACK)).toBe(1);
  });
});

describe('the run page, when a poll fails behind the run on screen', () => {
  it('keeps the run and leaves the failure to the toast', async () => {
    getJob.mockResolvedValue(JOB);
    await mount();
    await advance(0);
    expect(text()).toContain('Tidal energy storage');
    getJob.mockRejectedValue(failures.noWords());
    // The next poll (every five seconds), and its one retry a second later.
    await advance(5000);
    await advance(1000);
    expect(toastMessages()).toEqual(['Request failed with status code 500']);
    expect(text()).toContain('Tidal energy storage');
    expect(text()).not.toContain(FAILED);
    expect(text()).not.toContain(FALLBACK);
  });
});
