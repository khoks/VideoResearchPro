/**
 * S-8.10.1: the first-run wizard against mocked APIs. Each step does its
 * real action (PATCH the state, create the run from the starter template,
 * approve, finish), Skip records the dismissal, and the `/` gate sends an
 * account to the wizard only when the server says so.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WelcomePage } from '../WelcomePage';
import { OnboardingGate } from '../../components/onboarding/OnboardingGate';
import type { Onboarding, OnboardingPatch } from '../../services/onboardingApi';
import type { Job } from '../../types/job';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getMock = vi.fn<() => Promise<Onboarding>>();
const patchMock = vi.fn<(body: OnboardingPatch) => Promise<Onboarding>>();
const createMock = vi.fn();
const jobGetMock = vi.fn<(id: string) => Promise<Job>>();
const videosMock = vi.fn();
const approveMock = vi.fn();

vi.mock('../../services/onboardingApi', async (orig) => ({
  ...(await orig<typeof import('../../services/onboardingApi')>()),
  onboardingApi: { get: () => getMock(), patch: (b: OnboardingPatch) => patchMock(b) },
}));
vi.mock('../../services/jobsApi', () => ({
  jobsApi: {
    create: (...a: unknown[]) => createMock(...a),
    get: (id: string) => jobGetMock(id),
    getVideos: (id: string) => videosMock(id),
    approve: (...a: unknown[]) => approveMock(...a),
  },
}));
vi.mock('../../services/jobTemplatesApi', () => ({
  jobTemplatesApi: {
    list: () =>
      Promise.resolve([
        {
          id: 'tpl-channel',
          name: 'Channel deep-dive',
          builtin: true,
          builtin_key: 'channel-deep-dive',
          version: 2,
          job_type: 'channel',
          parameters: { job_type: 'channel', num_videos: 10, videos_per_channel: 25, min_duration_minutes: null, max_duration_minutes: null, output_length: null },
          problems: [],
        },
      ]),
  },
}));
vi.mock('../../services/wsClient', () => ({ wsClient: { subscribe: () => () => undefined } }));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));

function payload(over: Omit<Partial<Onboarding>, 'state'> & { state?: Partial<Onboarding['state']> } = {}): Onboarding {
  const { state, ...rest } = over;
  return {
    onboarded_at: null,
    started: false,
    should_onboard: true,
    milestones: { jobs: 0, first_job: null, report_opened: false, questions: 0 },
    ...rest,
    state: {
      step: 1,
      choices: { channels: [], first_job_id: null },
      dismissed: false,
      started_at: null,
      completed_at: null,
      dismissed_at: null,
      checklist_dismissed: false,
      checklist_dismissed_at: null,
      ...state,
    },
  };
}

function job(over: Partial<Job>): Job {
  return {
    id: 'job-1', job_type: 'channel', status: 'searching', created_at: '', updated_at: '', completed_at: null,
    topic: null, search_instructions: null, num_videos: 5, min_duration_minutes: null, max_duration_minutes: null,
    channel_type_filters: null, preferred_channels: null, channel_list: ['@a'], videos_per_channel: 5,
    output_length: null, visual_analysis: false, template_id: null, template_version: null, progress_pct: 10,
    progress_message: null, error_message: null, video_count: 0, transcript_count: 0, has_report: false,
    ...over,
  };
}

let host: HTMLDivElement;
let root: Root;
/** Renders the current path so a test reads it from the DOM. */
function Where() {
  return <output data-where>{useLocation().pathname}</output>;
}

async function flush(times = 6) {
  for (let i = 0; i < times; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(initial = '/welcome') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[initial]}>
          <Routes>
            <Route path="/" element={<OnboardingGate />} />
            <Route path="/welcome" element={<WelcomePage />} />
            <Route path="*" element={null} />
          </Routes>
          <Where />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const where = () => host.querySelector('[data-where]')?.textContent;
const heading = () => host.querySelector('h2')?.textContent ?? '';
const button = (text: string) =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === text) as HTMLButtonElement | undefined;

async function click(el: HTMLElement | undefined) {
  expect(el).toBeTruthy();
  await act(async () => {
    el!.click();
  });
  await flush();
}

function typeInto(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  // Merge the way onboarding_service.update does, over whatever GET served.
  patchMock.mockImplementation(async (b) => {
    const cur = await getMock();
    const choices = {
      channels: b.channels ?? cur.state.choices.channels,
      first_job_id: b.first_job_id ?? cur.state.choices.first_job_id,
    };
    return payload({
      ...cur,
      started: true,
      onboarded_at: b.completed ? '2026-10-19T12:00:00Z' : cur.onboarded_at,
      state: { ...cur.state, step: b.step ?? cur.state.step, choices, dismissed: b.dismissed || cur.state.dismissed },
    });
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('WelcomePage', () => {
  it('step 1 keeps valid channels and saves them with the next step', async () => {
    getMock.mockResolvedValue(payload());
    await mount();
    expect(heading()).toBe('Choose channels you trust');
    expect(button('Continue')!.disabled).toBe(true);

    const input = host.querySelector('input')!;
    typeInto(input, 'not a channel');
    await click(button('Add'));
    expect(host.querySelector('[role="alert"]')?.textContent).toMatch(/does not look like a YouTube channel/);

    typeInto(input, '@3blue1brown');
    await click(button('Add'));
    expect(host.querySelector('[aria-label="Chosen channels"]')?.textContent).toContain('@3blue1brown');

    await click(button('Continue'));
    expect(patchMock).toHaveBeenCalledWith({ step: 2, channels: ['@3blue1brown'] });
    expect(heading()).toBe('Start a small run');
    // Step 2 reads the saved channels: the first is chosen and the run can start.
    expect(host.querySelector<HTMLInputElement>('input[type="radio"]')!.checked).toBe(true);
    expect(button('Start the run')!.disabled).toBe(false);
  });

  it('step 2 starts a five-video channel run from the starter template', async () => {
    getMock.mockResolvedValue(payload({ started: true, state: { step: 2, choices: { channels: ['@a', '@b'], first_job_id: null } } }));
    createMock.mockResolvedValue(job({ id: 'job-9' }));
    jobGetMock.mockResolvedValue(job({ id: 'job-9' }));
    await mount();
    expect(heading()).toBe('Start a small run');

    const radios = host.querySelectorAll<HTMLInputElement>('input[type="radio"]');
    await click(radios[1]);
    await click(button('Start the run'));

    expect(createMock).toHaveBeenCalledWith(
      { job_type: 'channel', channel_list: ['@b'], videos_per_channel: 5, num_videos: 5 },
      { templateId: 'tpl-channel', templateVersion: 2 },
    );
    expect(patchMock).toHaveBeenCalledWith({ step: 3, first_job_id: 'job-9' });
    expect(heading()).toBe('It is reading');
  });

  it('step 3 approves every video the run found', async () => {
    getMock.mockResolvedValue(payload({ started: true, state: { step: 3, choices: { channels: ['@a'], first_job_id: 'job-1' } } }));
    jobGetMock.mockResolvedValue(job({ status: 'awaiting_approval' }));
    videosMock.mockResolvedValue([
      { id: 'r1', video_id: 'v1', document_id: 'd1', title: 'First video' },
      { id: 'r2', video_id: null, document_id: 'd2', title: 'Second video' },
    ]);
    approveMock.mockResolvedValue(job({ status: 'extracting' }));
    await mount();
    expect(heading()).toBe('Approve what it found');
    expect(host.textContent).toContain('Second video');

    await click(button('Approve these 2 videos'));
    expect(approveMock).toHaveBeenCalledWith('job-1', { approved_video_ids: ['v1', 'd2'] });
  });

  it('reading the report finishes the wizard and opens the reader', async () => {
    getMock.mockResolvedValue(payload({ started: true, state: { step: 3, choices: { channels: ['@a'], first_job_id: 'job-1' } } }));
    jobGetMock.mockResolvedValue(job({ status: 'completed', has_report: true, transcript_count: 5, progress_pct: 100 }));
    await mount();
    expect(heading()).toBe('Your report is ready');

    await click(button('Read the report'));
    expect(patchMock).toHaveBeenCalledWith({ completed: true });
    expect(where()).toBe('/reports/job-1');
  });

  it('a failed first run offers another go', async () => {
    getMock.mockResolvedValue(payload({ started: true, state: { step: 3, choices: { channels: ['@a'], first_job_id: 'job-1' } } }));
    jobGetMock.mockResolvedValue(job({ status: 'failed', error_message: 'None of the 1 channel(s) could be resolved.' }));
    await mount();
    expect(heading()).toBe('The run did not finish');
    expect(host.textContent).toContain('could be resolved');
    await click(button('Try again'));
    expect(heading()).toBe('Start a small run');
  });

  it('Skip records the dismissal and leaves for the submit page', async () => {
    getMock.mockResolvedValue(payload());
    await mount();
    await click(button('Skip for now'));
    expect(patchMock).toHaveBeenCalledWith({ dismissed: true });
    expect(where()).toBe('/submit');
  });
});

describe('OnboardingGate', () => {
  it('sends an account the server marks to the wizard', async () => {
    getMock.mockResolvedValue(payload({ should_onboard: true }));
    await mount('/');
    expect(where()).toBe('/welcome');
  });

  it('sends everyone else to the submit page', async () => {
    getMock.mockResolvedValue(payload({ should_onboard: false }));
    await mount('/');
    expect(where()).toBe('/submit');
  });

  it('never blocks the app when the state cannot be read', async () => {
    getMock.mockRejectedValue(new Error('down'));
    await mount('/');
    expect(where()).toBe('/submit');
  });
});
