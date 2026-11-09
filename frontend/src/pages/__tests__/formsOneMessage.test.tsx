/**
 * T-3.4.1.22 at the forms that say a failure in a dialog, and at the run's
 * approval, under the app's own query client and on the pages that open them.
 *
 * `ShelfFormModal` and `SaveTemplateModal` await the `onSubmit` their page hands
 * them and say a rejection in the dialog; the run's approval section does the
 * same with `onApprove`. The mutation behind each did not set `meta`, so the
 * global toast said the failure again. Now `useCreateShelf`, `useUpdateShelf`,
 * `useCreateTemplate`, `useSaveJobAsTemplate` and `useApproveJob` set it (every
 * caller shows a line), `useUpdateTemplate` takes `{ inlineErrors }` (the
 * templates page's rename passes it, the submit form's "Save changes" shows no
 * line and keeps the toast), and a 401 says nothing. Each dialog waits for its
 * answer: Escape and the backdrop do nothing while a save is in flight, as
 * Cancel already did. A run's Cancel waits for an approval in flight, since a
 * cancel would take the approval section and its line away.
 *
 * "A message" here is a toast or a line with `role="alert"` (the dialogs' line
 * is a form field's error, so it is read from there too).
 *
 * Mutation checks, run on 2026-11-09: taking `meta` off `useCreateShelf` or
 * `useApproveJob`, or `{ inlineErrors: true }` off the templates page's
 * `useUpdateTemplate`, fails that site's `words`, `noWords` and `noAnswer` rows
 * with the line and a toast; setting `meta` for every caller of
 * `useUpdateTemplate`, `useRemoveJobFromShelf` or `useCreateJob` fails "Save
 * changes keeps its toast", "a shelf's Remove keeps its toast" or "a failed run
 * keeps its toast" with no message at all; `apiErrorMessage` back in either
 * dialog, or in the approval section, fails its `sessionEnded` rows with "Not
 * authenticated"; either dialog's `dismiss` letting Escape or the backdrop close
 * while busy fails its "waits for a save in flight"; the run's Cancel without
 * `disabled={approveJob.isPending}` fails "waits for an approval in flight"; and
 * the shelf form resetting whenever `initial` is a new object fails the shelves
 * page's edit rows with no message at all.
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job } from '../../types/job';
import type { Video } from '../../types/video';
import type { JobTemplate } from '../../services/jobTemplatesApi';
import type { Shelf, ShelfDetail } from '../../services/shelvesApi';
import { createQueryClient } from '../../services/queryClient';
import { useJobStore } from '../../stores/jobStore';
import {
  FAILURE_KINDS,
  SERVER_WORDS,
  clearToasts,
  expectedToasts,
  failures,
  flush,
  press,
  toastMessages,
  typeInto,
} from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const TEMPLATE: JobTemplate = {
  id: 'tpl-1',
  name: 'Weekly tariffs',
  description: null,
  job_type: 'topic',
  builtin: false,
  builtin_key: null,
  version: 1,
  parameters: { job_type: 'topic', num_videos: 10, channel_list: null } as unknown as JobTemplate['parameters'],
  problems: [],
  created_at: '2026-11-01T09:00:00Z',
  updated_at: '2026-11-01T09:00:00Z',
};

const SHELF: Shelf = {
  id: 'shelf-1',
  name: 'Trade',
  description: null,
  color: 'default',
  job_count: 1,
  job_ids: ['job-1'],
  created_at: '2026-11-01T09:00:00Z',
  updated_at: '2026-11-01T09:00:00Z',
};

const JOB: Job = {
  id: 'job-1',
  job_type: 'topic',
  status: 'awaiting_approval',
  created_at: '2026-10-20T10:00:00Z',
  updated_at: '2026-10-20T11:00:00Z',
  completed_at: null,
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
  progress_pct: 30,
  progress_message: 'Waiting for approval',
  error_message: null,
  video_count: 1,
  transcript_count: 0,
  has_report: false,
};

const SHELF_DETAIL: ShelfDetail = { ...SHELF, jobs: [{ ...JOB, status: 'completed' }] };

const VIDEO = {
  id: 'd1',
  video_id: 'v1',
  document_id: 'd1',
  // An unregistered type renders the compact fallback row: no card config needed.
  source_type: 'fixture',
  source_id: 'v1',
  source_url: null,
  source_metadata: {},
  classification: null,
  title: 'Candidate one',
  channel_name: 'C',
  channel_id: null,
  url: 'https://example.com/1',
  duration_seconds: 60,
  published_at: null,
  thumbnail_url: null,
  approved: true,
  transcript_status: 'pending',
  transcript_word_count: null,
  transcript_language: null,
} as unknown as Video;

// ---------------------------------------------------------------------------
// The API, steered per test
// ---------------------------------------------------------------------------

const api = {
  createShelf: vi.fn<(body: unknown) => Promise<Shelf>>(),
  updateShelf: vi.fn<(id: string, body: unknown) => Promise<Shelf>>(),
  removeJob: vi.fn<(id: string, jobId: string) => Promise<void>>(),
  createTemplate: vi.fn<(body: unknown) => Promise<JobTemplate>>(),
  updateTemplate: vi.fn<(id: string, body: unknown) => Promise<JobTemplate>>(),
  saveJobAsTemplate: vi.fn<(jobId: string, body: unknown) => Promise<JobTemplate>>(),
  approve: vi.fn<(id: string, body: unknown) => Promise<Job>>(),
  cancel: vi.fn<(id: string) => Promise<Job>>(),
  createJob: vi.fn<(...a: unknown[]) => Promise<Job>>(),
};

vi.mock('../../services/shelvesApi', async (orig) => ({
  ...(await orig<typeof import('../../services/shelvesApi')>()),
  shelvesApi: {
    list: async () => [SHELF],
    get: async () => SHELF_DETAIL,
    create: (body: unknown) => api.createShelf(body),
    update: (id: string, body: unknown) => api.updateShelf(id, body),
    remove: async () => undefined,
    addJob: async () => SHELF,
    removeJob: (id: string, jobId: string) => api.removeJob(id, jobId),
    documents: async () => [],
    questions: async () => [],
    ask: vi.fn(),
  },
}));
vi.mock('../../services/jobTemplatesApi', () => ({
  jobTemplatesApi: {
    list: async () => [TEMPLATE],
    versions: async () => [],
    create: (body: unknown) => api.createTemplate(body),
    update: (id: string, body: unknown) => api.updateTemplate(id, body),
    remove: async () => undefined,
    saveJobAsTemplate: (jobId: string, body: unknown) => api.saveJobAsTemplate(jobId, body),
  },
}));
vi.mock('../../services/jobsApi', () => ({
  jobsApi: {
    get: async () => JOB,
    getVideos: async () => [VIDEO],
    approve: (id: string, body: unknown) => api.approve(id, body),
    cancel: (id: string) => api.cancel(id),
    delete: async () => undefined,
    create: (...a: unknown[]) => api.createJob(...a),
  },
}));
vi.mock('../../services/libraryQaApi', () => ({ libraryQaApi: { clarify: vi.fn() } }));
vi.mock('../../services/wsClient', () => ({ wsClient: { subscribe: () => () => undefined } }));
vi.mock('../../hooks/useJobProgress', () => ({ useJobProgress: () => undefined }));
vi.mock('../../hooks/useQA', () => ({
  useQAHistory: () => ({ data: [] }),
  useAskQuestion: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useAskQuestionStreaming: () => ({ askStreaming: vi.fn(), stage: null, isStreaming: false }),
  useClarifyQuestion: () => ({ mutateAsync: vi.fn(), isPending: false }),
  QAStreamHttpError: class extends Error {},
}));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../hooks/useCapability', () => ({ useCapability: () => false }));
vi.mock('../../hooks/useTierCapabilities', () => ({
  useTierCapabilities: () => ({ has: () => true, tier: 'studio', numVideosCap: 100 }),
}));
vi.mock('../../hooks/useOnboarding', () => ({ useOnboarding: () => ({ data: undefined }) }));
vi.mock('../../hooks/useExchangeFocus', () => ({ useExchangeFocus: () => undefined }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));
vi.mock('../../components/qa/SuggestionCard', () => ({ SuggestionCard: () => null }));
vi.mock('../../components/qa/Composer', () => ({
  QADock: ({ children }: { children: ReactNode }) => <>{children}</>,
  QAThread: ({ children }: { children: ReactNode }) => <>{children}</>,
  DockedComposer: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock('../../components/library/DocumentsBrowser', () => ({ DocumentsBrowser: () => null }));
vi.mock('../../components/citation', () => ({ CitationLink: () => null }));
vi.mock('../../components/savedSearches/PinQuestionButton', () => ({ PinQuestionButton: () => null }));

import { ShelvesPage } from '../ShelvesPage';
import { ShelfPage } from '../ShelfPage';
import { TemplatesPage } from '../TemplatesPage';
import { JobDetailPage } from '../JobDetailPage';
import { SubmitJobPage } from '../SubmitJobPage';

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

let host: HTMLDivElement;
let root: Root;

async function mount(path: string, routes: ReactNode, state?: unknown) {
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={[{ pathname: path, state }]}>
          <Routes>
            {routes}
            <Route path="*" element={null} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const shelvesPage = () => mount('/shelves', <Route path="/shelves" element={<ShelvesPage />} />);
const shelfPage = () => mount('/shelves/shelf-1', <Route path="/shelves/:shelfId" element={<ShelfPage />} />);
const templatesPage = () => mount('/templates', <Route path="/templates" element={<TemplatesPage />} />);
const jobPage = () => mount('/jobs/job-1', <Route path="/jobs/:jobId" element={<JobDetailPage />} />);
const submitPage = (state?: unknown) => mount('/submit', <Route path="/submit" element={<SubmitJobPage />} />, state);

/** Every failure said on screen: the error toasts, then each line with
 * `role="alert"` (a dialog's line is its name field's error, which has one). */
function messages(): string[] {
  const toasts = useJobStore.getState().toasts.filter((t) => t.kind === 'error').map((t) => t.message);
  const lines = Array.from(document.querySelectorAll('[role="alert"]')).map((el) => el.textContent?.trim() ?? '');
  return [...toasts, ...lines.filter(Boolean)];
}

/** The approval section's button, whose count follows the selection. */
async function approve() {
  const b = Array.from(host.querySelectorAll('button')).find((el) => el.textContent?.includes('Approve & continue'));
  if (!b) throw new Error('No approve button');
  await act(async () => b.click());
  await flush();
}

const dialog = () => document.querySelector('[role="dialog"]');

function nameField(): HTMLInputElement {
  return dialog()!.querySelector('input') as HTMLInputElement;
}

function pressEscape() {
  act(() => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  });
}

function clickBackdrop() {
  const backdrop = document.querySelector<HTMLElement>('[role="presentation"]');
  if (!backdrop) throw new Error('No modal backdrop');
  act(() => backdrop.click());
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

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  for (const fn of Object.values(api)) fn.mockReset();
  api.createShelf.mockResolvedValue(SHELF);
  api.updateShelf.mockResolvedValue(SHELF);
  api.removeJob.mockResolvedValue(undefined);
  api.createTemplate.mockResolvedValue(TEMPLATE);
  api.updateTemplate.mockResolvedValue(TEMPLATE);
  api.saveJobAsTemplate.mockResolvedValue(TEMPLATE);
  api.approve.mockResolvedValue({ ...JOB, status: 'extracting' });
  api.cancel.mockResolvedValue({ ...JOB, status: 'cancelled' });
  window.localStorage.clear();
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.localStorage.clear();
});

// ---------------------------------------------------------------------------
// One message per failure
// ---------------------------------------------------------------------------

const SITES = [
  {
    name: 'a new shelf',
    open: async () => {
      await shelvesPage();
      await press('New shelf');
      typeInto(nameField(), 'Energy');
      await press('Create shelf');
    },
    call: () => api.createShelf,
    fallback: 'Could not save the shelf.',
  },
  {
    name: 'editing a shelf, on the shelves page',
    open: async () => {
      await shelvesPage();
      await press('Edit');
      await press('Save');
    },
    call: () => api.updateShelf,
    fallback: 'Could not save the shelf.',
  },
  {
    name: 'editing a shelf, on its own page',
    open: async () => {
      await shelfPage();
      await press('Edit');
      await press('Save');
    },
    call: () => api.updateShelf,
    fallback: 'Could not save the shelf.',
  },
  {
    name: 'renaming a template',
    open: async () => {
      await templatesPage();
      await press('Rename');
      await press('Save');
    },
    call: () => api.updateTemplate,
    fallback: 'Could not save the template.',
  },
  {
    name: 'saving a run as a template',
    open: async () => {
      await jobPage();
      await press('Save as template');
      typeInto(nameField(), 'Tides');
      await press('Save template');
    },
    call: () => api.saveJobAsTemplate,
    fallback: 'Could not save the template.',
  },
  {
    name: 'saving the submit form as a template',
    open: async () => {
      window.localStorage.setItem('vrp:submit-form', JSON.stringify({ jobType: 'topic', topic: 'Tidal energy storage' }));
      await submitPage();
      await press('Save as template');
      typeInto(nameField(), 'Tides');
      await press('Save template');
    },
    call: () => api.createTemplate,
    fallback: 'Could not save the template.',
  },
  {
    name: 'approving a run',
    open: async () => {
      await jobPage();
      await approve();
    },
    call: () => api.approve,
    fallback: 'The approval did not go through. Try again.',
  },
];

describe.each(SITES)('$name', (site) => {
  it.each(FAILURE_KINDS)('says a failure (%s) once, where it was asked', async (kind) => {
    site.call().mockRejectedValueOnce(failures[kind]());
    await site.open();
    expect(site.call()).toHaveBeenCalledTimes(1);
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(expectedToasts(kind, site.fallback));
  });

  it('says nothing when it goes through', async () => {
    await site.open();
    expect(site.call()).toHaveBeenCalledTimes(1);
    expect(messages()).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Callers with no line keep the global toast
// ---------------------------------------------------------------------------

describe('callers that show no line', () => {
  it('Save changes keeps its toast: the submit form says no line of its own', async () => {
    api.updateTemplate.mockRejectedValueOnce(failures.words());
    await submitPage({ fromTemplateId: TEMPLATE.id });
    await press('Save changes as v2');
    expect(api.updateTemplate).toHaveBeenCalledTimes(1);
    expect(messages()).toEqual([SERVER_WORDS]);
  });

  it('a shelf’s Remove keeps its toast: the shelf page says no line of its own', async () => {
    api.removeJob.mockRejectedValueOnce(failures.words());
    await shelfPage();
    await press('Remove');
    expect(api.removeJob).toHaveBeenCalledWith('shelf-1', 'job-1');
    expect(messages()).toEqual([SERVER_WORDS]);
  });

  it('a failed run keeps its toast: the submit form says only a full library itself', async () => {
    api.createJob.mockRejectedValueOnce(failures.words());
    window.localStorage.setItem('vrp:submit-form', JSON.stringify({ jobType: 'topic', topic: 'Tidal energy storage' }));
    await submitPage();
    const submit = host.querySelector('button[type="submit"]') as HTMLButtonElement;
    await act(async () => submit.click());
    await flush();
    expect(api.createJob).toHaveBeenCalledTimes(1);
    expect(messages()).toEqual([SERVER_WORDS]);
  });
});

// ---------------------------------------------------------------------------
// Waiting for the answer
// ---------------------------------------------------------------------------

describe.each([
  {
    name: 'the shelf form',
    open: async () => {
      await shelvesPage();
      await press('New shelf');
      typeInto(nameField(), 'Energy');
    },
    submit: 'Create shelf',
    call: () => api.createShelf,
    fallback: 'Could not save the shelf.',
  },
  {
    name: 'the template dialog',
    open: async () => {
      await jobPage();
      await press('Save as template');
      typeInto(nameField(), 'Tides');
    },
    submit: 'Save template',
    call: () => api.saveJobAsTemplate,
    fallback: 'Could not save the template.',
  },
])('$name', (site) => {
  it('waits for a save in flight, then says its failure', async () => {
    const request = held<never>();
    site.call().mockReturnValueOnce(request.promise);
    await site.open();
    await press(site.submit);
    pressEscape();
    clickBackdrop();
    await flush();
    expect(dialog()).not.toBeNull();
    await act(async () => request.fail(failures.noWords()));
    await flush();
    expect(dialog()).not.toBeNull();
    expect(messages()).toEqual([site.fallback]);
    pressEscape();
    await flush();
    expect(dialog()).toBeNull();
  });
});

describe('a run’s approval', () => {
  it('waits for an approval in flight before Cancel goes', async () => {
    const request = held<Job>();
    api.approve.mockReturnValueOnce(request.promise);
    await jobPage();
    await approve();
    const cancel = Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Cancel') as HTMLButtonElement;
    expect(cancel.disabled).toBe(true);
    await act(async () => request.fail(failures.words()));
    await flush();
    expect(messages()).toEqual([SERVER_WORDS]);
    expect(cancel.disabled).toBe(false);
    expect(api.cancel).not.toHaveBeenCalled();
  });
});
