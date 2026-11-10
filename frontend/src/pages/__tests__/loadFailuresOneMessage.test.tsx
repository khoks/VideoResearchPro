/**
 * T-3.4.1.26: one message per failed load, under the app's own query client.
 *
 * The `QueryCache` toasted every failed query, so a page that also said a
 * load's failure in a line of its own ("Could not load your notes.") said it
 * twice. Now a reader that says the failure on the page sets `meta`
 * (`ERRORS_SHOWN_HERE`, or `LOAD_ERRORS_SHOWN_HERE` for a line shown only in
 * place of a first load), and the toast stands aside while such a reader is
 * mounted. Each line says the server's words through `inlineErrorMessage`,
 * else its own sentence, and nothing for a 401. A reader that shows no line
 * keeps the toast, alone or beside a page that does not show the query.
 *
 * Retries are as the app has them: one, a second after the first failure, and
 * the toast (or not) only once that fails too. The tests run on fake timers
 * that move that second on.
 *
 * Mutation checks, run on 2026-11-10: taking `meta` off `useNotesList`,
 * `useSavedSearches`, `useDraftStatus` or `useEchoFootprint`, or
 * `{ inlineErrors: true }` off the shelves page, fails that page's `words`,
 * `noWords` and `noAnswer` rows with a toast beside the line (and the notes
 * page's failed refresh, and the shelves pair); the old fixed sentence back on
 * the saved searches page fails its `words` row, and `apiErrorMessage` in
 * place of `inlineErrorMessage` on "Speak as me" its `sessionEnded` row with
 * "Not authenticated"; reading `query.meta` (the last reader's) in place of
 * each mounted reader's in `queryFailureShownOnPage` fails "a page left before
 * its load fails leaves the failure to the toast" and "one reader that says it
 * is enough"; dropping its `enabled` check fails "counts only a mounted,
 * enabled reader"; treating `'load'` as `true` fails the data card's failed
 * refresh and "stands aside only while there is no data"; and
 * `inlineErrors: true` in place of `tab === 'channels'` on the library fails
 * "the sources tab leaves a failed channels read to the toast", and in place of
 * `tab === 'videos'` fails "the channels tab leaves a failed sources read to the
 * toast".
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider, QueryObserver } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { NoteListResponse } from '../../services/notesApi';
import type { SavedSearchList } from '../../services/savedSearchesApi';
import type { DraftStatus, EchoFootprint } from '../../services/echoApi';
import type { Shelf } from '../../services/shelvesApi';
import type { Channel } from '../../services/channelsApi';
import {
  ERRORS_SHOWN_HERE,
  LOAD_ERRORS_SHOWN_HERE,
  createQueryClient,
  queryFailureShownOnPage,
} from '../../services/queryClient';
import { useShelves } from '../../hooks/useShelves';
import {
  FAILURE_KINDS,
  SERVER_WORDS,
  clearToasts,
  failures,
  flush,
  toastMessages,
  type FailureKind,
} from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const NOTES: NoteListResponse = {
  items: [
    {
      id: 'note-a',
      target_type: 'document',
      target_id: 'doc-1',
      body_md: 'A thought worth keeping.',
      motivation: 'commenting',
      selector: null,
      created_at: '2026-11-01T09:00:00Z',
      updated_at: '2026-11-01T09:00:00Z',
      deleted_at: null,
      target_label: 'A source',
      target_video_id: null,
    },
  ],
  total: 1,
  limit: 2000,
  offset: 0,
};
const SAVED: SavedSearchList = { items: [], active: 0, cap: 10 };
const STATUS: DraftStatus = {
  enabled: false,
  blockers: [{ code: 'install_off', message: 'Drafting is off on this install.' }],
  readiness: {},
  voice_gate: { status: 'not_run', run_at: null, pairs: 0, picked_own_share: null, notes_total: 0, notes_needed: 40 },
  drafts_today: 0,
  drafts_per_day: 20,
  state: 'install_off',
  reasons: [],
  notes: 0,
  notes_needed: 40,
  pairs_judged: 0,
  pairs_needed: 20,
} as DraftStatus;
const FOOTPRINT: EchoFootprint = { rows: { personal_context: 3 }, files: 0, vectors: {} } as EchoFootprint;
const SHELF: Shelf = {
  id: 'shelf-1',
  name: 'Tariffs',
  description: null,
  color: 'accent',
  job_ids: [],
  created_at: '2026-11-01T09:00:00Z',
  updated_at: '2026-11-01T09:00:00Z',
} as unknown as Shelf;
const CHANNEL = { id: 'UC1', channel_id: 'UC1', name: 'First channel', subscribed: false, source_weight: 1, video_count: 3 } as Channel;

// ---------------------------------------------------------------------------
// The API, steered per test
// ---------------------------------------------------------------------------

const api = {
  notes: vi.fn<() => Promise<NoteListResponse>>(),
  saved: vi.fn<() => Promise<SavedSearchList>>(),
  draftStatus: vi.fn<() => Promise<DraftStatus>>(),
  footprint: vi.fn<() => Promise<EchoFootprint>>(),
  shelves: vi.fn<() => Promise<Shelf[]>>(),
  channels: vi.fn<() => Promise<Channel[]>>(),
  suggestions: vi.fn<() => Promise<unknown>>(),
  videos: vi.fn<() => Promise<unknown[]>>(),
};

vi.mock('../../services/notesApi', async (orig) => ({
  ...(await orig<typeof import('../../services/notesApi')>()),
  notesApi: { list: () => api.notes() },
}));
vi.mock('../../services/savedSearchesApi', () => ({ savedSearchesApi: { list: () => api.saved() } }));
vi.mock('../../services/echoApi', () => ({
  echoApi: {
    draftStatus: () => api.draftStatus(),
    footprint: () => api.footprint(),
    listDrafts: async () => ({ items: [] }),
    voiceTest: async () => ({
      offer: { available: false, blockers: [], pairs: 20, model_calls: 40, model: 'm', notes: 0, notes_needed: 40, pass_share: 0.8, tests_today: 0, tests_per_day: 3 },
      gate: { status: 'not_run', run_at: null, pairs: 0, picked_own_share: null, notes_total: 0, notes_needed: 40 },
      test: null,
    }),
  },
}));
vi.mock('../../services/shelvesApi', async (orig) => ({
  ...(await orig<typeof import('../../services/shelvesApi')>()),
  shelvesApi: { list: () => api.shelves() },
}));
vi.mock('../../services/channelsApi', () => ({ channelsApi: { list: () => api.channels() } }));
vi.mock('../../services/libraryApi', async (orig) => ({
  ...(await orig<typeof import('../../services/libraryApi')>()),
  libraryApi: { listVideos: () => api.videos() },
}));
vi.mock('../../services/suggestionsApi', () => ({ suggestionsApi: { get: () => api.suggestions() } }));
vi.mock('../../components/library/PdfUploadZone', () => ({ PdfUploadZone: () => null }));
vi.mock('../../components/library/PasteUrlsForm', () => ({ PasteUrlsForm: () => null }));
vi.mock('../../components/tags', () => ({ TagFilterBar: () => null }));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../hooks/useTierCapabilities', () => ({
  useTierCapabilities: () => ({ has: () => true, tier: 'studio', isLoading: false }),
}));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));

import { EchoDataCard } from '../../components/echo/EchoDataCard';
import { SpeakAsMePanel } from '../../components/echo/SpeakAsMePanel';
import { SuggestionCard } from '../../components/qa/SuggestionCard';
import { LibraryPage } from '../LibraryPage';
import { NotesPage } from '../NotesPage';
import { SavedSearchesPage } from '../SavedSearchesPage';
import { ShelvesPage } from '../ShelvesPage';

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

let host: HTMLDivElement;
let root: Root;

async function mount(node: ReactNode, path = '/', client: QueryClient = createQueryClient()) {
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

/** Lets a failed first try reach its one retry, a second later, and settle. */
async function settle() {
  await flush();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  await flush();
}

const text = () => host.textContent ?? '';
const count = (haystack: string, needle: string) => haystack.split(needle).length - 1;

/** What the global toast says for a failure: the server's words, else axios's,
 * and nothing for a 401 (`globalErrorToastMessage`). */
function toastFor(kind: FailureKind): string[] {
  return {
    words: [SERVER_WORDS],
    noWords: ['Request failed with status code 500'],
    noAnswer: ['Network Error'],
    sessionEnded: [],
  }[kind];
}

/** One message for a failed load: no toast, and the line once, with the
 * server's words or the page's sentence; for a 401, neither. */
function expectSaidOnce(kind: FailureKind, { title, fallback }: { title?: string; fallback: string }) {
  expect(toastMessages()).toEqual([]);
  if (kind === 'sessionEnded') {
    expect(text()).not.toContain(fallback);
    if (title) expect(text()).not.toContain(title);
    expect(text()).not.toContain('Not authenticated');
    return;
  }
  expect(count(text(), kind === 'words' ? SERVER_WORDS : fallback)).toBe(1);
  if (kind === 'words' && title) expect(text()).toContain(title);
  expect(text()).not.toMatch(/Network Error|status code 500/);
}

/** A test reader of the shelves list that shows nothing of a failure, as the
 * sidebar and the "Add to shelf" pickers do. */
function ShelvesCount() {
  const { data } = useShelves();
  return <p data-shelves-count>{data?.length ?? 0} shelves</p>;
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  for (const fn of Object.values(api)) fn.mockReset();
  api.notes.mockResolvedValue(NOTES);
  api.saved.mockResolvedValue(SAVED);
  api.draftStatus.mockResolvedValue(STATUS);
  api.footprint.mockResolvedValue(FOOTPRINT);
  api.shelves.mockResolvedValue([SHELF]);
  api.channels.mockResolvedValue([CHANNEL]);
  api.suggestions.mockResolvedValue({ suggestions: [] });
  api.videos.mockResolvedValue([]);
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// A page that says a failed load says it once
// ---------------------------------------------------------------------------

const PAGES: Array<{
  name: string;
  fail: (err: unknown) => void;
  open: () => Promise<void>;
  title?: string;
  fallback: string;
}> = [
  {
    name: 'the notes page',
    fail: (e) => api.notes.mockRejectedValue(e),
    open: () => mount(<NotesPage />),
    fallback: 'Could not load your notes.',
  },
  {
    name: 'the saved searches page',
    fail: (e) => api.saved.mockRejectedValue(e),
    open: () => mount(<SavedSearchesPage />),
    title: "Couldn't load your saved searches.",
    fallback: 'Something blocked the request.',
  },
  {
    name: 'the "Speak as me" card',
    fail: (e) => api.draftStatus.mockRejectedValue(e),
    open: () => mount(<SpeakAsMePanel />),
    fallback: "Couldn't check whether drafting is on.",
  },
  {
    name: "Echo's data card (a line in place of a first load)",
    fail: (e) => api.footprint.mockRejectedValue(e),
    open: () => mount(<EchoDataCard />),
    fallback: "Couldn't read what Echo holds.",
  },
  {
    name: 'the shelves page',
    fail: (e) => api.shelves.mockRejectedValue(e),
    open: () => mount(<ShelvesPage />),
    title: "Couldn't load your shelves.",
    fallback: 'Something blocked the fetch.',
  },
  {
    name: "the library's channels tab",
    fail: (e) => api.channels.mockRejectedValue(e),
    open: () => mount(<LibraryPage />, '/library?tab=channels'),
    title: "Couldn't load channels.",
    fallback: 'Something blocked the channels fetch.',
  },
  {
    name: "the library's sources tab",
    fail: (e) => api.videos.mockRejectedValue(e),
    open: () => mount(<LibraryPage />, '/library?tab=videos'),
    title: "Couldn't load your sources.",
    fallback: 'Something blocked the library fetch.',
  },
];

describe.each(PAGES)('$name', (page) => {
  it.each(FAILURE_KINDS)('says a failed load once (%s)', async (kind) => {
    page.fail(failures[kind]());
    await page.open();
    await settle();
    expectSaidOnce(kind, page);
  });
});

describe('a failure said nowhere else keeps its toast', () => {
  it.each(FAILURE_KINDS)('the suggestion card, which hides itself (%s)', async (kind) => {
    api.suggestions.mockRejectedValue(failures[kind]());
    await mount(<SuggestionCard context="library" onFill={() => undefined} />);
    await settle();
    expect(toastMessages()).toEqual(toastFor(kind));
  });

  it.each(FAILURE_KINDS)('a reader with no line alone keeps the toast (%s)', async (kind) => {
    api.shelves.mockRejectedValue(failures[kind]());
    await mount(<ShelvesCount />);
    await settle();
    expect(toastMessages()).toEqual(toastFor(kind));
  });

  it('beside the page that says it, the same key is said once, by the page', async () => {
    api.shelves.mockRejectedValue(failures.noWords());
    await mount(
      <>
        <ShelvesCount />
        <ShelvesPage />
      </>,
    );
    await settle();
    expectSaidOnce('noWords', { title: "Couldn't load your shelves.", fallback: 'Something blocked the fetch.' });
  });

  it('a page left before its load fails leaves the failure to the toast', async () => {
    let fail: (e: unknown) => void = () => undefined;
    api.notes.mockReturnValue(new Promise<NoteListResponse>((_, reject) => (fail = reject)));
    await mount(<NotesPage />);
    act(() => root.render(<p>elsewhere</p>));
    await act(async () => fail(failures.noWords()));
    await settle();
    expect(toastMessages()).toEqual(['Request failed with status code 500']);
  });

  it("the sources tab leaves a failed channels read to the toast, since only the channels tab says it", async () => {
    api.channels.mockRejectedValue(failures.noWords());
    await mount(<LibraryPage />, '/library?tab=videos');
    await settle();
    expect(toastMessages()).toEqual(['Request failed with status code 500']);
    expect(text()).not.toContain("Couldn't load channels.");
  });

  it('the channels tab leaves a failed sources read to the toast, since only the sources tab says it', async () => {
    api.videos.mockRejectedValue(failures.noWords());
    await mount(<LibraryPage />, '/library?tab=channels');
    await settle();
    expect(toastMessages()).toEqual(['Request failed with status code 500']);
    expect(text()).not.toContain("Couldn't load your sources.");
  });
});

describe('a refresh that fails', () => {
  it('says it once on a page whose line shows over what it had read', async () => {
    const client = createQueryClient();
    await mount(<NotesPage />, '/', client);
    await settle();
    expect(text()).toContain('A thought worth keeping.');
    api.notes.mockRejectedValue(failures.noWords());
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['notes'] });
    });
    await settle();
    expectSaidOnce('noWords', { fallback: 'Could not load your notes.' });
  });

  it('keeps its toast behind counts still on screen, where no line shows', async () => {
    const client = createQueryClient();
    await mount(<EchoDataCard />, '/', client);
    await settle();
    expect(text()).toContain('3 facts');
    api.footprint.mockRejectedValue(failures.noWords());
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['echo', 'footprint'] });
    });
    await settle();
    expect(toastMessages()).toEqual(['Request failed with status code 500']);
    expect(text()).toContain('3 facts');
    expect(text()).not.toContain("Couldn't read what Echo holds.");
  });
});

// ---------------------------------------------------------------------------
// The rule itself
// ---------------------------------------------------------------------------

describe('queryFailureShownOnPage', () => {
  const never = () => new Promise<number>(() => undefined);
  const queryOf = (client: QueryClient) => client.getQueryCache().find({ queryKey: ['k'] })!;

  it('counts only a mounted, enabled reader', () => {
    const client = new QueryClient();
    const reader = new QueryObserver(client, { queryKey: ['k'], queryFn: never, meta: ERRORS_SHOWN_HERE, enabled: false });
    const stop = reader.subscribe(() => undefined);
    expect(queryFailureShownOnPage(queryOf(client))).toBe(false);
    reader.setOptions({ queryKey: ['k'], queryFn: never, meta: ERRORS_SHOWN_HERE, enabled: true });
    expect(queryFailureShownOnPage(queryOf(client))).toBe(true);
    stop();
    expect(queryFailureShownOnPage(queryOf(client))).toBe(false);
  });

  it('a line in place of a first load stands aside only while there is no data', () => {
    const client = new QueryClient();
    const stop = new QueryObserver(client, { queryKey: ['k'], queryFn: never, meta: LOAD_ERRORS_SHOWN_HERE }).subscribe(() => undefined);
    expect(queryFailureShownOnPage(queryOf(client))).toBe(true);
    client.setQueryData(['k'], 1);
    expect(queryFailureShownOnPage(queryOf(client))).toBe(false);
    stop();
  });

  it('one reader that says it is enough, and a reader that does not is not', () => {
    const client = new QueryClient();
    const silent = new QueryObserver(client, { queryKey: ['k'], queryFn: never }).subscribe(() => undefined);
    expect(queryFailureShownOnPage(queryOf(client))).toBe(false);
    const said = new QueryObserver(client, { queryKey: ['k'], queryFn: never, meta: ERRORS_SHOWN_HERE }).subscribe(() => undefined);
    expect(queryFailureShownOnPage(queryOf(client))).toBe(true);
    said();
    expect(queryFailureShownOnPage(queryOf(client))).toBe(false);
    silent();
  });
});
