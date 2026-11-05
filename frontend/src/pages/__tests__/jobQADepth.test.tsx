/**
 * R4 / S-1.15.2: the job Q&A panel's per-ask depth control. The router has
 * taken `output_length` since 2026-10-19 (the request's value, else the job's
 * own) but the page never sent one. The control starts on Default, which
 * names the run's own depth when it has one; the ask carries
 * `output_length` only when a depth was picked, on the streaming path, its
 * non-streaming fallback and a Shift-clicked suggestion alike. A pick is for
 * that one ask: it clears when the answer lands, and until then it shows in the
 * docked composer, where a phone reader has lost sight of the select.
 *
 * T-1.15.3.9: the panel starts from the account's default depth on a run with no
 * depth of its own, and returns to it after an ask. T-1.15.4.5: a cut-off answer's
 * card (`answerCutOff.test.tsx` has the note itself). Mutation checks, run by hand
 * on 2026-11-04: `finishAsk` setting null in place of the reset fails "goes back to
 * the preference"; starting from the preference on a run with a depth fails
 * "leaves a run's own depth alone"; the card not passing `runDepth` fails "a run
 * asked for at Deep".
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job } from '../../types/job';
import type { QAExchange, QARequest } from '../../types/qa';
import { useQACutOffStore } from '../../stores/qaCutOffStore';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let job: Job;
let history: QAExchange[] = [];
let streamStatus = 0; // 0: the stream answers; otherwise it fails with this HTTP status
const streamed: QARequest[] = [];
const posted: QARequest[] = [];
const clarify = vi.fn(async () => ({ interpretation: 'You mean tidal storage costs.', clarifications: [] }));

// Hoisted with the mocks: the page checks `instanceof QAStreamHttpError`.
const { StreamError } = vi.hoisted(() => {
  class StreamError extends Error {
    status: number;
    constructor(status: number) {
      super(`status ${status}`);
      this.status = status;
    }
  }
  return { StreamError };
});

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
  useQAHistory: () => ({ data: history }),
  useAskQuestion: () => ({
    mutateAsync: async (data: QARequest) => {
      posted.push(data);
    },
    isPending: false,
  }),
  useAskQuestionStreaming: () => ({
    askStreaming: async (data: QARequest) => {
      if (streamStatus) throw new StreamError(streamStatus);
      streamed.push(data);
    },
    stage: null,
    isStreaming: false,
  }),
  useClarifyQuestion: () => ({ mutateAsync: clarify, isPending: false }),
  QAStreamHttpError: StreamError,
}));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../hooks/useTierCapabilities', () => ({ useTierCapabilities: () => ({ has: () => false }) }));
vi.mock('../../hooks/useJobTemplates', () => ({ useSaveJobAsTemplate: () => ({ mutateAsync: vi.fn() }) }));
vi.mock('../../hooks/useExchangeFocus', () => ({ useExchangeFocus: () => undefined }));
vi.mock('../../components/templates', () => ({ SaveTemplateModal: () => null }));
vi.mock('../../components/shelves', () => ({ JobShelfChips: () => null, ShelfPicker: () => null }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));
vi.mock('../../components/qa/SuggestionCard', () => ({
  SuggestionCard: ({ onAsk }: { onAsk: (q: string) => void }) => (
    <button type="button" data-testid="suggestion" onClick={() => onAsk('What does a lagoon cost?')}>
      suggestion
    </button>
  ),
}));
vi.mock('../../components/qa/Composer', () => ({
  QADock: ({ children }: { children: ReactNode }) => <>{children}</>,
  QAThread: ({ children }: { children: ReactNode }) => <>{children}</>,
  DockedComposer: ({ children }: { children: ReactNode }) => <div data-testid="composer">{children}</div>,
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

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

function mount(preferred: string | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(['auth', 'me'], { preferred_output_length: preferred });
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

const depthSelect = () => host.querySelector<HTMLSelectElement>('select[aria-label="Answer depth"]');

function pick(depth: string) {
  const select = depthSelect()!;
  act(() => {
    select.value = depth;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

const composer = () => host.querySelector('[data-testid="composer"]');
const buttonLabelled = (label: string) =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as HTMLButtonElement;

/** Type the question and press Ask, which opens the clarify step. */
async function startAsk(question: string) {
  const input = host.querySelector<HTMLInputElement>('input[placeholder="Ask a question about the research…"]')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(input, question);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  act(() => {
    input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}

async function ask(question: string) {
  await startAsk(question);
  await act(async () => buttonLabelled('Skip clarifications').click());
  await flush();
}

beforeEach(() => {
  job = JOB;
  history = [];
  useQACutOffStore.setState({ answers: {} });
  streamStatus = 0;
  streamed.length = 0;
  posted.length = 0;
  clarify.mockClear();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('JobDetailPage Q&A: a cut-off answer (T-1.15.4.5)', () => {
  const CUT: QAExchange = {
    id: 'q1',
    question: 'What does a lagoon cost?',
    answer: 'A lagoon costs',
    references: [],
    created_at: '2026-11-04T00:00:00Z',
  };
  const NOTE = 'This answer stopped at its length limit';
  const OFFER = 'Ask again at Deep depth';

  it('says so under the answer, and the offer fills the composer at Deep', async () => {
    history = [CUT];
    useQACutOffStore.getState().note('q1', null);
    mount();
    expect(host.querySelector('#exchange-q1')!.textContent).toContain(NOTE);

    await act(async () => buttonLabelled(OFFER).click());
    await flush();
    const input = host.querySelector<HTMLInputElement>('input[placeholder="Ask a question about the research…"]')!;
    expect(input.value).toBe(CUT.question);
    expect(depthSelect()!.value).toBe('deep');
    expect(streamed).toEqual([]);
  });

  it('gives an answer on a run asked for at Deep the note alone', async () => {
    job = { ...JOB, output_length: 'deep' };
    history = [CUT];
    useQACutOffStore.getState().note('q1', null);
    mount();
    expect(host.querySelector('#exchange-q1')!.textContent).toContain(NOTE);
    expect(buttonLabelled(OFFER)).toBeUndefined();
  });

  it('says nothing of an answer it did not see cut', () => {
    history = [CUT];
    mount();
    expect(host.querySelector('[data-answer-cut-off]')).toBeNull();
  });
});

describe("JobDetailPage Q&A: the account's default depth (T-1.15.3.9)", () => {
  it('starts a run that has no depth from the preference, and sends it', async () => {
    mount('brief');
    expect(depthSelect()!.value).toBe('brief');
    await ask('What does a lagoon cost?');
    expect(streamed).toEqual([{ question: 'What does a lagoon cost?', output_length: 'brief' }]);
  });

  it('goes back to the preference once an answer lands', async () => {
    mount('brief');
    pick('deep');
    await ask('What does a lagoon cost?');
    expect(streamed[0].output_length).toBe('deep');
    expect(depthSelect()!.value).toBe('brief');
  });

  it("leaves a run's own depth alone: that was chosen on a page", async () => {
    job = { ...JOB, output_length: 'standard' };
    mount('brief');
    expect(depthSelect()!.value).toBe('');
    expect(depthSelect()!.options[0].textContent).toBe('Default (standard)');
    await ask('What does a lagoon cost?');
    expect('output_length' in streamed[0]).toBe(false);
  });

  it('lets Default win for the ask it was picked for', async () => {
    mount('brief');
    pick('');
    await ask('What does a lagoon cost?');
    expect('output_length' in streamed[0]).toBe(false);
  });

  it('shows the preference in the docked composer on phones, where the select scrolls away', async () => {
    mount('brief');
    expect(composer()!.textContent).toContain('Answer depth: Brief');
  });
});

describe('JobDetailPage Q&A: answer depth', () => {
  it('renders on Default, and sends no output_length when left there', async () => {
    mount();
    const select = depthSelect();
    expect(select).not.toBeNull();
    expect(Array.from(select!.options).map((o) => o.textContent)).toEqual(['Default', 'Brief', 'Standard', 'Deep']);
    expect(select!.value).toBe('');

    await ask('What does a lagoon cost?');
    expect(streamed).toEqual([{ question: 'What does a lagoon cost?' }]);
    expect('output_length' in streamed[0]).toBe(false);
  });

  it("names the run's own depth as the default, and still sends nothing for it", async () => {
    // The router falls back to job.output_length, so sending it is redundant.
    job = { ...JOB, output_length: 'deep' };
    mount();
    expect(depthSelect()!.options[0].textContent).toBe('Default (deep)');
    await ask('What does a lagoon cost?');
    expect('output_length' in streamed[0]).toBe(false);
  });

  it('sends the chosen depth for the ask, overriding the run', async () => {
    job = { ...JOB, output_length: 'deep' };
    mount();
    pick('brief');
    await ask('What does a lagoon cost?');
    expect(streamed).toEqual([{ question: 'What does a lagoon cost?', output_length: 'brief' }]);
  });

  it('sends it on the non-streaming fallback too', async () => {
    streamStatus = 404; // the stream endpoint is not deployed
    mount();
    pick('standard');
    await ask('What does a lagoon cost?');
    expect(posted).toEqual([{ question: 'What does a lagoon cost?', output_length: 'standard' }]);
  });

  it('sends it with a suggestion asked at once', async () => {
    mount();
    pick('deep');
    await act(async () => host.querySelector<HTMLButtonElement>('[data-testid="suggestion"]')!.click());
    await flush();
    expect(streamed).toEqual([{ question: 'What does a lagoon cost?', output_length: 'deep' }]);
  });

  it('applies to that one ask: the next request omits it and the control is back on Default', async () => {
    job = { ...JOB, output_length: 'deep' };
    mount();
    pick('brief');
    await ask('What does a lagoon cost?');
    expect(streamed[0].output_length).toBe('brief');
    expect(depthSelect()!.value).toBe('');

    await ask('How long does one last?');
    expect(streamed).toHaveLength(2);
    expect('output_length' in streamed[1]).toBe(false);
  });

  it('clears after a suggestion is answered too', async () => {
    mount();
    pick('deep');
    await act(async () => host.querySelector<HTMLButtonElement>('[data-testid="suggestion"]')!.click());
    await flush();
    expect(depthSelect()!.value).toBe('');
  });

  it('stays for the retry when the ask fails', async () => {
    streamStatus = 500;
    mount();
    pick('brief');
    await ask('What does a lagoon cost?');
    expect(depthSelect()!.value).toBe('brief');
  });

  it('stays through "Edit question", which is still the same ask', async () => {
    mount();
    pick('brief');
    await startAsk('What does a lagoon cost?');
    const edit = Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.includes('Edit question'))!;
    act(() => edit.click());
    expect(depthSelect()!.value).toBe('brief');
    await ask('What does a tidal lagoon cost?');
    expect(streamed).toEqual([{ question: 'What does a tidal lagoon cost?', output_length: 'brief' }]);
  });

  it('shows a picked depth in the docked composer, and drops it from there', () => {
    mount();
    expect(composer()!.textContent).not.toContain('Answer depth:');
    pick('brief');
    expect(composer()!.textContent).toContain('Answer depth: Brief');
    act(() => buttonLabelled('Clear').click());
    expect(depthSelect()!.value).toBe('');
    expect(composer()!.textContent).not.toContain('Answer depth:');
  });
});
