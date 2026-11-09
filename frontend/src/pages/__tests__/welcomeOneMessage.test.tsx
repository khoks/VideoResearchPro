/**
 * T-3.4.1.22 and T-3.4.1.23 on the first-run wizard, under the app's own query
 * client.
 *
 * T-3.4.1.22: saving the channels, starting the run and approving said a failure
 * under their buttons and in the global toast. Now each is said there alone: the
 * wizard's two line-bearing saves and its start take `{ inlineErrors: true }`,
 * `useApproveJob` sets `meta` (both its callers show a line), and a 401 says
 * nothing. While one is in flight, Back, the steps and Skip wait, since each
 * would take the line away before it is written. The wizard's other saves (a
 * step, Skip, finishing) and the jobs page's checklist show no line, so the
 * global toast still says theirs.
 *
 * T-3.4.1.23: one `catch` caught a failed start and a failed save of the step
 * after it, and said "The run could not be started" for both, with "Start the
 * run" still on offer, so a run that had started could be started again. Now a
 * run that started is said to have started, the step offers no second start,
 * and the reader can still carry on to its progress.
 *
 * "A message" here is a toast or a line with `role="alert"`.
 *
 * Mutation checks, run on 2026-11-09:
 * - `useCreateJob` with no `{ inlineErrors: true }` in the wizard fails the
 *   start rows but `sessionEnded` with the line and a toast; the same goes for
 *   the wizard's `saveStep` and the channels and record rows, and for `meta`
 *   taken off `useApproveJob` and the approval rows.
 * - `apiErrorMessage` back in place of `inlineErrorMessage` at the start's line
 *   fails its `sessionEnded` row with "Not authenticated".
 * - The old single `catch` around the start and the record fails every "records
 *   the run" row ("Start the run" is offered again), "lets the reader carry on"
 *   and "back on the step".
 * - The Back button without `held` fails "waits for a start in flight"; Skip
 *   without `skipHeld` fails all three "waits for" tests.
 * - `meta` set on every `useUpdateOnboarding` fails "a step's failed save" and
 *   "the jobs page checklist" with no message at all, and the guard's third half.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryClient } from '../../services/queryClient';
import type { Onboarding, OnboardingPatch } from '../../services/onboardingApi';
import type { Job } from '../../types/job';
import {
  FAILURE_KINDS,
  SERVER_WORDS,
  clearToasts,
  expectedToasts,
  failures,
  flush,
  toastMessages,
} from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getMock = vi.fn<() => Promise<Onboarding>>();
const patchMock = vi.fn<(body: OnboardingPatch) => Promise<Onboarding>>();
const createMock = vi.fn<(...a: unknown[]) => Promise<Job>>();
const jobGetMock = vi.fn<(id: string) => Promise<Job>>();
const videosMock = vi.fn();
const approveMock = vi.fn<(...a: unknown[]) => Promise<Job>>();

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
          parameters: { job_type: 'channel', num_videos: 10, videos_per_channel: 25 },
          problems: [],
        },
      ]),
  },
}));
vi.mock('../../services/wsClient', () => ({ wsClient: { subscribe: () => () => undefined } }));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));

import { WelcomePage } from '../WelcomePage';
import { ChecklistCard } from '../../components/onboarding/ChecklistCard';

function payload(over: Omit<Partial<Onboarding>, 'state'> & { state?: Partial<Onboarding['state']> } = {}): Onboarding {
  const { state, ...rest } = over;
  return {
    onboarded_at: null,
    started: true,
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
    id: 'job-9', job_type: 'channel', status: 'searching', created_at: '', updated_at: '', completed_at: null,
    topic: null, search_instructions: null, num_videos: 5, min_duration_minutes: null, max_duration_minutes: null,
    channel_type_filters: null, preferred_channels: null, channel_list: ['@a'], videos_per_channel: 5,
    output_length: null, visual_analysis: false, template_id: null, template_version: null, progress_pct: 10,
    progress_message: null, error_message: null, video_count: 0, transcript_count: 0, has_report: false,
    ...over,
  };
}

/** A request that answers when the test says. */
function held<T>() {
  let fail: (reason: unknown) => void = () => undefined;
  let land: (value: T) => void = () => undefined;
  const promise = new Promise<T>((resolve, reject) => {
    land = resolve;
    fail = reject;
  });
  return { promise, fail, land };
}

let host: HTMLDivElement;
let root: Root;

function Where() {
  return <output data-where>{useLocation().pathname}</output>;
}

async function mount(node = <WelcomePage />) {
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={['/welcome']}>
          <Routes>
            <Route path="/welcome" element={node} />
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
/** A step the stepper lets the reader go back to. */
const stepButton = (label: string) =>
  Array.from(host.querySelectorAll('ol[aria-label="Getting started"] button')).find((b) =>
    b.textContent?.includes(label),
  ) as HTMLButtonElement | undefined;

async function click(el: HTMLElement | undefined) {
  expect(el).toBeTruthy();
  await act(async () => {
    el!.click();
  });
  await flush();
}

/** Every message on screen: the toasts, then each line with `role="alert"`. */
function messages(): string[] {
  const lines = Array.from(host.querySelectorAll('[role="alert"]')).map((el) => el.textContent?.trim() ?? '');
  return [...toastMessages(), ...lines];
}

/** The PATCH answers as `onboarding_service.update` merges, over what GET served. */
function patchMerges() {
  patchMock.mockImplementation(async (b) => {
    const cur = await getMock();
    return payload({
      ...cur,
      state: {
        ...cur.state,
        step: b.step ?? cur.state.step,
        choices: {
          channels: b.channels ?? cur.state.choices.channels,
          first_job_id: b.first_job_id ?? cur.state.choices.first_job_id,
        },
        dismissed: b.dismissed || cur.state.dismissed,
      },
    });
  });
}

const STEP_ONE = payload({ state: { step: 1, choices: { channels: ['@a'], first_job_id: null } } });
const STEP_TWO = payload({ state: { step: 2, choices: { channels: ['@a'], first_job_id: null } } });
const STEP_THREE = payload({ state: { step: 3, choices: { channels: ['@a'], first_job_id: 'job-1' } } });

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  vi.clearAllMocks();
  patchMerges();
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

// ---------------------------------------------------------------------------
// One message per failure
// ---------------------------------------------------------------------------

describe('saving the channels', () => {
  it.each(FAILURE_KINDS)('says a failure (%s) once, under Continue', async (kind) => {
    getMock.mockResolvedValue(STEP_ONE);
    patchMock.mockRejectedValueOnce(failures[kind]());
    await mount();
    await click(button('Continue'));
    expect(patchMock).toHaveBeenCalledWith({ step: 2, channels: ['@a'] });
    expect(heading()).toBe('Choose channels you trust');
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(expectedToasts(kind, 'Your channels could not be saved. Try again.'));
  });
});

describe('starting the run', () => {
  it.each(FAILURE_KINDS)('says a failure (%s) once, and the run can be started again', async (kind) => {
    getMock.mockResolvedValue(STEP_TWO);
    createMock.mockRejectedValueOnce(failures[kind]());
    await mount();
    await click(button('Start the run'));
    expect(createMock).toHaveBeenCalledTimes(1);
    expect(patchMock).not.toHaveBeenCalled();
    expect(heading()).toBe('Start a small run');
    expect(button('Start the run')).toBeTruthy();
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(
      expectedToasts(kind, 'The run could not be started. Check the channel and try again.'),
    );
  });

  it('goes on to the progress when the run starts and is recorded', async () => {
    getMock.mockResolvedValue(STEP_TWO);
    createMock.mockResolvedValue(job({}));
    jobGetMock.mockResolvedValue(job({}));
    await mount();
    await click(button('Start the run'));
    expect(patchMock).toHaveBeenCalledWith({ step: 3, first_job_id: 'job-9' });
    expect(heading()).toBe('It is reading');
    expect(messages()).toEqual([]);
  });
});

describe('a run that started and could not be recorded (T-3.4.1.23)', () => {
  const FALLBACK = 'This page could not record it, so carry on from here or find it under Active runs.';

  it.each(FAILURE_KINDS)('records the run: says it started, once (%s), and offers no second start', async (kind) => {
    getMock.mockResolvedValue(STEP_TWO);
    createMock.mockResolvedValue(job({}));
    jobGetMock.mockResolvedValue(job({}));
    patchMock.mockRejectedValueOnce(failures[kind]());
    await mount();
    await click(button('Start the run'));
    expect(createMock).toHaveBeenCalledTimes(1);
    expect(patchMock).toHaveBeenCalledWith({ step: 3, first_job_id: 'job-9' });
    expect(heading()).toBe('Your first run is under way');
    expect(host.textContent).not.toContain('could not be started');
    expect(button('Start the run')).toBeUndefined();
    expect(toastMessages()).toEqual([]);
    const said = kind === 'sessionEnded' ? [] : [`The run started. ${kind === 'words' ? SERVER_WORDS : FALLBACK}`];
    expect(messages()).toEqual(said);
  });

  it('lets the reader carry on to the run it started, and records it on the way', async () => {
    getMock.mockResolvedValue(STEP_TWO);
    createMock.mockResolvedValue(job({}));
    jobGetMock.mockResolvedValue(job({ progress_message: 'Fetching transcripts.' }));
    patchMock.mockRejectedValueOnce(failures.noWords());
    await mount();
    await click(button('Start the run'));
    await click(button('See its progress'));
    expect(heading()).toBe('It is reading');
    expect(jobGetMock).toHaveBeenCalledWith('job-9');
    expect(patchMock).toHaveBeenLastCalledWith({ step: 3, first_job_id: 'job-9' });
    expect(createMock).toHaveBeenCalledTimes(1);
  });

  it('back on the step, still offers no second start while the run goes on', async () => {
    getMock.mockResolvedValue(STEP_TWO);
    createMock.mockResolvedValue(job({}));
    jobGetMock.mockResolvedValue(job({}));
    patchMock.mockRejectedValueOnce(failures.noWords());
    await mount();
    await click(button('Start the run'));
    await click(button('Back'));
    expect(heading()).toBe('Choose channels you trust');
    await click(button('Continue'));
    expect(heading()).toBe('Your first run is under way');
    expect(button('Start the run')).toBeUndefined();
  });

  it('offers another start once that run has failed', async () => {
    getMock.mockResolvedValue(STEP_TWO);
    createMock.mockResolvedValue(job({}));
    jobGetMock.mockResolvedValue(job({ status: 'failed' }));
    patchMock.mockRejectedValueOnce(failures.noWords());
    await mount();
    await click(button('Start the run'));
    expect(heading()).toBe('Start a small run');
    expect(button('Start the run')).toBeTruthy();
  });
});

describe('approving what the run found', () => {
  it.each(FAILURE_KINDS)('says a failure (%s) once, under the button', async (kind) => {
    getMock.mockResolvedValue(STEP_THREE);
    jobGetMock.mockResolvedValue(job({ id: 'job-1', status: 'awaiting_approval' }));
    videosMock.mockResolvedValue([{ id: 'r1', video_id: 'v1', document_id: 'd1', title: 'First video' }]);
    approveMock.mockRejectedValueOnce(failures[kind]());
    await mount();
    await click(button('Approve this video'));
    expect(approveMock).toHaveBeenCalledWith('job-1', { approved_video_ids: ['v1'] });
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(expectedToasts(kind, 'The approval did not go through. Try again.'));
  });
});

// ---------------------------------------------------------------------------
// Saves with no line of their own keep the global toast
// ---------------------------------------------------------------------------

describe('saves that show no line', () => {
  it('a step’s failed save is said once, by the global toast', async () => {
    getMock.mockResolvedValue(STEP_TWO);
    patchMock.mockRejectedValueOnce(failures.words());
    await mount();
    await click(button('Back'));
    expect(patchMock).toHaveBeenCalledWith({ step: 1 });
    expect(messages()).toEqual([SERVER_WORDS]);
  });

  it('the jobs page checklist says a failed hide once, by the global toast', async () => {
    getMock.mockResolvedValue(payload());
    patchMock.mockRejectedValueOnce(failures.words());
    await mount(<ChecklistCard />);
    await click(button('Hide this'));
    expect(patchMock).toHaveBeenCalledWith({ checklist_dismissed: true });
    expect(messages()).toEqual([SERVER_WORDS]);
  });
});

// ---------------------------------------------------------------------------
// Waiting for the answer
// ---------------------------------------------------------------------------

describe('while a request is in flight', () => {
  it('waits for a start in flight: Back, the steps and Skip, then says its failure', async () => {
    getMock.mockResolvedValue(STEP_TWO);
    const request = held<Job>();
    createMock.mockReturnValueOnce(request.promise);
    await mount();
    await click(button('Start the run'));
    expect(button('Back')!.disabled).toBe(true);
    expect(button('Skip for now')!.disabled).toBe(true);
    await click(stepButton('Choose channels'));
    await click(button('Skip for now'));
    expect(heading()).toBe('Start a small run');
    expect(where()).toBe('/welcome');
    expect(patchMock).not.toHaveBeenCalled();
    await act(async () => request.fail(failures.noWords()));
    await flush();
    expect(messages()).toEqual(['The run could not be started. Check the channel and try again.']);
    expect(button('Back')!.disabled).toBe(false);
    expect(button('Skip for now')!.disabled).toBe(false);
  });

  it('waits for the run to be recorded before Skip goes', async () => {
    getMock.mockResolvedValue(STEP_TWO);
    createMock.mockResolvedValue(job({}));
    jobGetMock.mockResolvedValue(job({}));
    const record = held<Onboarding>();
    patchMock.mockReturnValueOnce(record.promise);
    await mount();
    await click(button('Start the run'));
    expect(button('Skip for now')!.disabled).toBe(true);
    await act(async () => record.fail(failures.words()));
    await flush();
    expect(messages()).toEqual([`The run started. ${SERVER_WORDS}`]);
    expect(button('Skip for now')!.disabled).toBe(false);
  });

  it('waits for an approval in flight before Skip goes', async () => {
    getMock.mockResolvedValue(STEP_THREE);
    jobGetMock.mockResolvedValue(job({ id: 'job-1', status: 'awaiting_approval' }));
    videosMock.mockResolvedValue([{ id: 'r1', video_id: 'v1', document_id: 'd1', title: 'First video' }]);
    const request = held<Job>();
    approveMock.mockReturnValueOnce(request.promise);
    await mount();
    await click(button('Approve this video'));
    expect(button('Skip for now')!.disabled).toBe(true);
    await act(async () => request.fail(failures.noAnswer()));
    await flush();
    expect(messages()).toEqual(['The approval did not go through. Try again.']);
    expect(button('Skip for now')!.disabled).toBe(false);
  });
});
