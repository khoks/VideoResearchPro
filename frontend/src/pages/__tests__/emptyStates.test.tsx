/**
 * S-8.10.2: empty states state what is true. Zero data is told apart from
 * "nothing matches" and from a failed fetch, each with its one action; the
 * first-run checklist sits on the jobs page until its three milestones are
 * met or it is hidden; the library Q&A page says there is nothing to ask
 * when the library is empty.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Onboarding } from '../../services/onboardingApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ── mocks ────────────────────────────────────────────────────────────────
const jobsState: { data?: unknown[]; isLoading: boolean; isError: boolean; refetch: () => void } = {
  data: [],
  isLoading: false,
  isError: false,
  refetch: vi.fn(),
};
vi.mock('../../hooks/useJobs', () => ({
  useJobs: () => jobsState,
  useCancelJob: () => ({ mutate: vi.fn() }),
  useDeleteJob: () => ({ mutate: vi.fn() }),
}));
vi.mock('../../hooks/useJobProgress', () => ({ useAllJobsProgress: () => undefined }));
vi.mock('../../components/shelves', () => ({ JobShelfChips: () => null, ShelfPicker: () => null }));

const onboardingGet = vi.fn<() => Promise<Onboarding>>();
const onboardingPatch = vi.fn();
vi.mock('../../services/onboardingApi', async (orig) => ({
  ...(await orig<typeof import('../../services/onboardingApi')>()),
  onboardingApi: { get: () => onboardingGet(), patch: (b: unknown) => onboardingPatch(b) },
}));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));

const librarySources: { data: unknown[] } = { data: [] };
const libraryHistory: { data: unknown[] } = { data: [] };
vi.mock('../../hooks/useLibrary', () => ({
  useLibraryVideos: () => ({ data: librarySources.data, isSuccess: true }),
}));
vi.mock('../../hooks/useLibraryQA', () => ({
  useLibraryQAHistory: () => ({ data: libraryHistory.data }),
  useAskLibraryQA: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useClarifyLibraryQA: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));

import { JobsListPage } from '../JobsListPage';
import { LibraryQAPage } from '../LibraryQAPage';

function onboarding(over: Partial<Onboarding['milestones']> = {}, state: Partial<Onboarding['state']> = {}): Onboarding {
  return {
    onboarded_at: null,
    started: false,
    should_onboard: false,
    milestones: { jobs: 0, first_job: null, report_opened: false, questions: 0, ...over },
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

// ── harness ──────────────────────────────────────────────────────────────
let host: HTMLDivElement;
let root: Root;

function Where() {
  const loc = useLocation();
  return <output data-where>{loc.pathname + loc.search}</output>;
}

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(element: React.ReactNode, path = '/jobs') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={path.split('?')[0]} element={element} />
            <Route path="*" element={null} />
          </Routes>
          <Where />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const text = () => host.textContent ?? '';
const button = (label: string) =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as HTMLButtonElement | undefined;
const where = () => host.querySelector('[data-where]')?.textContent;

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
  jobsState.data = [];
  jobsState.isLoading = false;
  jobsState.isError = false;
  librarySources.data = [];
  libraryHistory.data = [];
  onboardingGet.mockResolvedValue(onboarding());
  onboardingPatch.mockImplementation(async () => onboarding({}, { checklist_dismissed: true }));
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

// ── jobs page ────────────────────────────────────────────────────────────
describe('JobsListPage', () => {
  it('a new account sees the first-run state with one action', async () => {
    await mount(<JobsListPage />);
    expect(text()).toContain('Nothing researched yet.');
    act(() => button('New research')!.click());
    expect(where()).toBe('/submit');
  });

  it('an empty search is "nothing matches", with a way back, never the first-run copy', async () => {
    jobsState.data = [{ id: 'j1', job_type: 'topic', topic: 'tariffs', status: 'completed', created_at: '2026-10-01T00:00:00Z', channel_list: null, progress_pct: 100, video_count: 1, transcript_count: 1, has_report: true }];
    await mount(<JobsListPage />);
    typeInto(host.querySelector('input[aria-label="Search jobs"]')!, 'zzz');
    await flush();
    expect(text()).toContain('Nothing matches these filters.');
    expect(text()).not.toContain('Nothing researched yet.');
    act(() => button('Clear filters')!.click());
    await flush();
    expect(text()).not.toContain('Nothing matches these filters.');
  });

  it('a failed fetch says so and retries, instead of claiming there are no runs', async () => {
    jobsState.isError = true;
    jobsState.data = undefined;
    await mount(<JobsListPage />);
    expect(text()).toContain("Couldn't load your runs.");
    expect(text()).not.toContain('Nothing researched yet.');
    act(() => button('Retry')!.click());
    expect(jobsState.refetch).toHaveBeenCalled();
  });

  it('loads with skeletons, not a bare spinner', async () => {
    jobsState.isLoading = true;
    await mount(<JobsListPage />);
    expect(host.querySelector('[aria-busy]')).toBeTruthy();
  });
});

// ── checklist ────────────────────────────────────────────────────────────
describe('ChecklistCard on the jobs page', () => {
  it('lists the three milestones with what is done', async () => {
    onboardingGet.mockResolvedValue(
      onboarding({ jobs: 1, first_job: { id: 'j1', job_type: 'channel', status: 'completed', has_report: true } }),
    );
    await mount(<JobsListPage />);
    const card = host.querySelector('section[aria-labelledby="checklist-title"]')!;
    expect(card).toBeTruthy();
    expect(card.textContent).toContain('1 of 3 done');
    expect(card.textContent).toContain('Start a research run (done)');
    expect(card.querySelector('a[href="/reports/j1"]')).toBeTruthy();
    expect(card.querySelector('a[href="/jobs/j1"]')).toBeTruthy();
  });

  it('Hide this keeps it hidden on the server', async () => {
    await mount(<JobsListPage />);
    act(() => button('Hide this')!.click());
    await flush();
    expect(onboardingPatch).toHaveBeenCalledWith({ checklist_dismissed: true });
    expect(host.querySelector('section[aria-labelledby="checklist-title"]')).toBeNull();
  });

  it('is gone once all three are done, or once hidden', async () => {
    onboardingGet.mockResolvedValue(
      onboarding({ jobs: 3, report_opened: true, questions: 2, first_job: { id: 'j1', job_type: 'topic', status: 'completed', has_report: true } }),
    );
    await mount(<JobsListPage />);
    expect(host.querySelector('section[aria-labelledby="checklist-title"]')).toBeNull();
    act(() => root.unmount());
    root = createRoot(host);
    onboardingGet.mockResolvedValue(onboarding({}, { checklist_dismissed: true }));
    await mount(<JobsListPage />);
    expect(host.querySelector('section[aria-labelledby="checklist-title"]')).toBeNull();
  });
});

// ── library Q&A ──────────────────────────────────────────────────────────
describe('LibraryQAPage', () => {
  it('with an empty library there is nothing to ask, and one way to fix it', async () => {
    await mount(<LibraryQAPage />, '/library/qa');
    expect(text()).toContain('Nothing to ask yet.');
    expect(host.querySelector('form')).toBeNull();
    act(() => button('Add sources')!.click());
    expect(where()).toBe('/library?tab=ingest');
  });

  it('with sources the composer is there', async () => {
    librarySources.data = [{ id: 'd1' }];
    await mount(<LibraryQAPage />, '/library/qa');
    expect(text()).not.toContain('Nothing to ask yet.');
    expect(host.querySelector('form')).toBeTruthy();
  });
});

// ── copy guard ───────────────────────────────────────────────────────────
describe('editorial voice', () => {
  it('no page falls back to generic empty copy', () => {
    const sources = import.meta.glob('../*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
    expect(Object.keys(sources).length).toBeGreaterThan(20);
    const banned = /['">]\s*(No data\.?|No results\.?|Empty list\.?|Nothing here\.?)\s*['"<]/;
    const offenders = Object.entries(sources)
      .filter(([, src]) => banned.test(src))
      .map(([file]) => file);
    expect(offenders).toEqual([]);
  });
});
