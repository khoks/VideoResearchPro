/**
 * S-8.3.2: saved searches in the UI. The page lists each pinned question
 * with its schedule, next run and last answer, and its actions call the
 * API; "Pin this question" sends the exchange's question with a human
 * cadence in the reader's zone; both disappear for tiers without the
 * feature; the route is mounted.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { RouteObject } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SavedSearch, SavedSearchList } from '../../services/savedSearchesApi';
import { describeCadence, parseUtc } from '../../utils/cadence';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const api = {
  list: vi.fn<() => Promise<SavedSearchList>>(),
  create: vi.fn(async (b: unknown) => ({ id: 'new', ...(b as object) })),
  update: vi.fn(async (_id: string, b: unknown) => b),
  remove: vi.fn<(id: string) => Promise<undefined>>(async () => undefined),
  runNow: vi.fn<(id: string) => Promise<{ status: "queued" }>>(async () => ({ status: "queued" })),
};
vi.mock('../../services/savedSearchesApi', () => ({
  savedSearchesApi: {
    list: () => api.list(),
    create: (b: unknown) => api.create(b),
    update: (id: string, b: unknown) => api.update(id, b),
    remove: (id: string) => api.remove(id),
    runNow: (id: string) => api.runNow(id),
  },
}));
const tier = { saved: true, loading: false };
vi.mock('../../hooks/useTierCapabilities', () => ({
  useTierCapabilities: () => ({
    has: (f: string) => (f === 'saved_searches' ? tier.saved : true),
    tier: tier.saved ? 'pro' : 'free',
    isLoading: tier.loading,
  }),
}));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));

import { SavedSearchesPage } from '../SavedSearchesPage';
import { PinQuestionButton } from '../../components/savedSearches/PinQuestionButton';

const ROW: SavedSearch = {
  id: 'ss1',
  question: 'What do my sources say about rate cuts?',
  answer_language: 'en',
  scope: null,
  cadence: { cadence: 'weekly', hour: 9, minute: 0, weekday: 0, timezone: 'UTC' },
  next_run_at: '2026-10-26T09:00:00',
  notify_email: true,
  enabled: true,
  created_at: '2026-10-19T10:00:00',
  last_run_at: '2026-10-19T10:01:00',
  last_status: 'ok',
  last_error: null,
  last_success_at: '2026-10-19T10:01:00',
  last_exchange_id: 'ex1',
  last_answer: 'Two cuts so far this year.',
};

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

async function mount(node: React.ReactNode, path = '/saved-searches') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={path} element={node} />
            <Route path="*" element={null} />
          </Routes>
          <Where />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const button = (label: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as HTMLButtonElement | undefined;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  tier.saved = true;
  tier.loading = false;
  api.list.mockResolvedValue({ items: [ROW], active: 1, cap: 10 });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('cadence helpers', () => {
  it('describes presets in words, naming the zone only when it is not the reader’s', () => {
    expect(describeCadence({ cadence: 'daily', hour: 7, timezone: 'UTC' }, 'UTC')).toBe('Daily at 07:00');
    expect(describeCadence({ cadence: 'weekly', hour: 9, weekday: 4, timezone: 'Asia/Kolkata' }, 'UTC')).toBe(
      'Weekly on Friday at 09:00 (Asia/Kolkata)',
    );
    expect(describeCadence({ cadence: 'monthly', hour: 6, minute: 30, day_of_month: 2, timezone: 'UTC' }, 'UTC')).toBe(
      'Monthly on the 2nd at 06:30',
    );
  });

  it('reads the API’s naive timestamps as UTC', () => {
    expect(parseUtc('2026-10-26T09:00:00').toISOString()).toBe('2026-10-26T09:00:00.000Z');
  });
});

describe('SavedSearchesPage', () => {
  it('lists each search with its schedule, status and last answer', async () => {
    await mount(<SavedSearchesPage />);
    const text = host.textContent ?? '';
    expect(text).toContain('What do my sources say about rate cuts?');
    expect(text).toContain('Weekly on Monday at 09:00');
    expect(text).toContain('Answered');
    expect(text).toContain('Two cuts so far this year.');
    expect(text).toContain('1 of 10 active');
    expect(host.querySelector('a[href="/library/qa?exchange=ex1"]')).toBeTruthy();
  });

  it('Run now and Pause call the API', async () => {
    await mount(<SavedSearchesPage />);
    await act(async () => button('Run now')!.click());
    await flush();
    expect(api.runNow).toHaveBeenCalledWith('ss1');
    await act(async () => button('Pause')!.click());
    await flush();
    expect(api.update).toHaveBeenCalledWith('ss1', { enabled: false });
  });

  it('says what a skipped run means', async () => {
    api.list.mockResolvedValue({
      items: [{ ...ROW, last_status: 'quota_exceeded', last_error: 'Monthly library question quota reached; this run was skipped.' }],
      active: 1,
      cap: 10,
    });
    await mount(<SavedSearchesPage />);
    expect(host.textContent).toContain('Skipped: monthly quota');
    expect(host.textContent).toContain('this run was skipped');
  });

  it('with nothing pinned, points at library Q&A', async () => {
    api.list.mockResolvedValue({ items: [], active: 0, cap: 10 });
    await mount(<SavedSearchesPage />);
    expect(host.textContent).toContain('Nothing pinned yet.');
    act(() => button('Ask the library')!.click());
    expect(host.querySelector('[data-where]')?.textContent).toBe('/library/qa');
  });

  it('while the tier is loading, does not claim the plan lacks the feature', async () => {
    tier.saved = false;
    tier.loading = true;
    await mount(<SavedSearchesPage />);
    expect(host.textContent).not.toContain('come with Pro');
    expect(host.querySelector('[aria-busy]')).toBeTruthy();
  });

  it('on a tier without the feature, explains instead of fetching', async () => {
    tier.saved = false;
    await mount(<SavedSearchesPage />);
    expect(host.textContent).toContain('Saved searches come with Pro.');
    expect(api.list).not.toHaveBeenCalled();
  });
});

describe('PinQuestionButton', () => {
  it('pins the question weekly at 09:00 in the reader’s zone by default', async () => {
    await mount(<PinQuestionButton question="Why did rates fall?" answerLanguage="hi" />, '/library/qa');
    act(() => button('Pin this question')!.click());
    await flush();
    await act(async () => button('Pin it')!.click());
    await flush();
    const body = api.create.mock.calls[0][0] as { question: string; cadence: { cadence: string; hour: number; timezone: string }; answer_language: string; notify_email: boolean };
    expect(body.question).toBe('Why did rates fall?');
    expect(body.answer_language).toBe('hi');
    expect(body.cadence).toMatchObject({ cadence: 'weekly', hour: 9, weekday: 0 });
    expect(body.cadence.timezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
    expect(body.notify_email).toBe(true);
    expect(host.querySelector('a[href="/saved-searches"]')?.textContent).toBe('Pinned');
  });

  it('is absent on tiers without saved searches', async () => {
    tier.saved = false;
    await mount(<PinQuestionButton question="Why?" answerLanguage="en" />, '/library/qa');
    expect(button('Pin this question')).toBeUndefined();
  });
});

describe('wiring', () => {
  it('mounts /saved-searches and puts the pin on library Q&A answer cards', async () => {
    const { router } = await import('../../routes');
    const find = (routes: RouteObject[]): RouteObject | undefined => {
      for (const r of routes) {
        if (r.path === 'saved-searches') return r;
        const hit = r.children ? find(r.children) : undefined;
        if (hit) return hit;
      }
      return undefined;
    };
    expect((find(router.routes)?.element as { type?: unknown })?.type).toBe(SavedSearchesPage);
    const src = Object.values(
      import.meta.glob('../LibraryQAPage.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
    )[0];
    expect(src).toMatch(/<PinQuestionButton question=\{qa\.question\}/);
  });
});
