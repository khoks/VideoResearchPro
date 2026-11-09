/**
 * T-3.4.1.24 at the lines read from a mutation's state, under the app's own
 * query client: a frame capture, a pasted batch, a note written or edited (in
 * the notes panel and on the notes page), a pinned question and a saved
 * search's actions. Each page built a line from the mutation's `isError` while
 * the global toast said the same failure again; the guard's state reading found
 * them (T-3.4.1.22).
 *
 * Now each hook sets `meta: ERRORS_SHOWN_HERE` (every caller shows a line;
 * a note's delete shows none and keeps the toast), each line gives the
 * server's words through `inlineErrorMessage`, and a 401 says nothing. Every
 * control on a line's own surface waits for the answer (D-159 point 2): the
 * pin dialog's Cancel, Escape and backdrop; another note's Edit, Add a note and
 * the panel's fold; "See them on the shelf" while the next batch is out; and a
 * saved search's other changes while one is out, its Delete while anything on
 * the card is out, and everything while it is being deleted. A saved search's
 * three actions each have their own line, as D-159 point 3 asks.
 *
 * "A message" here is a toast or a line with `role="alert"`.
 *
 * Mutation checks, run on 2026-11-09: taking `meta` off `useExtractFrames`,
 * `usePasteUrls`, `useCreateNote`, `useUpdateNote`, `useCreateSavedSearch`,
 * `useUpdateSavedSearch`, `useRunSavedSearchNow` or `useDeleteSavedSearch`
 * fails that site's `words`, `noWords` and `noAnswer` rows with the line and a
 * toast; `apiErrorMessage` (or the old reading of `detail`) in place of
 * `inlineErrorMessage` fails the `sessionEnded` rows with "Not authenticated";
 * the panel's old `errorText` fails the frames' `noWords` and `noAnswer` rows
 * with axios's words; setting `meta` on `useDeleteNote` fails both "a note's
 * delete keeps its toast"; each hold taken out fails its "waits" test; the
 * saved search's one shared line back fails "each action has its own line";
 * and dropping the editor reset fails "a new editor starts clean".
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { AxiosError, AxiosHeaders } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FramesResponse } from '../../utils/frames';
import type { Note, NoteListResponse } from '../../services/notesApi';
import type { PasteUrlsResponse } from '../../services/libraryApi';
import type { SavedSearch, SavedSearchList } from '../../services/savedSearchesApi';
import { createQueryClient } from '../../services/queryClient';
import { useJobStore } from '../../stores/jobStore';
import { featureFlags } from '../../config/features';
import {
  FAILURE_KINDS,
  SERVER_WORDS,
  buttonsLabelled,
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

const FRAMES: FramesResponse = { document_id: 'd1', video_id: 'vid1', visual_enabled: true, in_progress: false, frames: [] };

function note(id: string, body: string): Note {
  return {
    id,
    target_type: 'document',
    target_id: 'doc-1',
    body_md: body,
    motivation: 'commenting',
    selector: null,
    created_at: '2026-11-01T09:00:00Z',
    updated_at: '2026-11-01T09:00:00Z',
    deleted_at: null,
    target_label: 'A source',
    target_video_id: null,
  };
}
const NOTE_A = note('note-a', 'First thought.');
const NOTE_B = note('note-b', 'Second thought.');
const NOTES: NoteListResponse = { items: [NOTE_A, NOTE_B], total: 2, limit: 2000, offset: 0 };

const SAVED: SavedSearch = {
  id: 'ss1',
  question: 'What do my sources say about rate cuts?',
  answer_language: 'en',
  scope: null,
  cadence: { cadence: 'weekly', hour: 9, minute: 0, weekday: 0, timezone: 'UTC' },
  next_run_at: '2026-11-16T09:00:00',
  notify_email: true,
  enabled: true,
  created_at: '2026-11-01T10:00:00',
  last_run_at: '2026-11-08T09:01:00',
  last_status: 'ok',
  last_error: null,
  last_success_at: '2026-11-08T09:01:00',
  last_exchange_id: 'ex1',
  last_answer: 'Two cuts so far this year.',
};
const SAVED_LIST: SavedSearchList = { items: [SAVED], active: 1, cap: 10 };

const PASTED: PasteUrlsResponse = {
  results: [{ url: 'https://example.com/a', status: 'created', document_id: 'doc-9', source_type: 'article', word_count: 900 }],
};

// ---------------------------------------------------------------------------
// The API, steered per test
// ---------------------------------------------------------------------------

const api = {
  extract: vi.fn<(id: string, force: boolean) => Promise<unknown>>(),
  pasteUrls: vi.fn<(urls: string[]) => Promise<PasteUrlsResponse>>(),
  createNote: vi.fn<(p: unknown) => Promise<Note>>(),
  updateNote: vi.fn<(id: string, p: unknown) => Promise<Note>>(),
  removeNote: vi.fn<(id: string) => Promise<unknown>>(),
  createSaved: vi.fn<(b: unknown) => Promise<SavedSearch>>(),
  updateSaved: vi.fn<(id: string, b: unknown) => Promise<SavedSearch>>(),
  runNow: vi.fn<(id: string) => Promise<unknown>>(),
  removeSaved: vi.fn<(id: string) => Promise<unknown>>(),
};

vi.mock('../../services/framesApi', () => ({
  framesApi: {
    list: async () => FRAMES,
    imageBlob: async () => new Blob(['jpeg']),
    extract: (id: string, force: boolean) => api.extract(id, force),
  },
}));
vi.mock('../../services/libraryApi', async (orig) => ({
  ...(await orig<typeof import('../../services/libraryApi')>()),
  libraryApi: { pasteUrls: (urls: string[]) => api.pasteUrls(urls) },
}));
vi.mock('../../services/notesApi', async (orig) => ({
  ...(await orig<typeof import('../../services/notesApi')>()),
  notesApi: {
    list: async () => NOTES,
    create: (p: unknown) => api.createNote(p),
    update: (id: string, p: unknown) => api.updateNote(id, p),
    remove: (id: string) => api.removeNote(id),
  },
}));
vi.mock('../../services/savedSearchesApi', () => ({
  savedSearchesApi: {
    list: async () => SAVED_LIST,
    create: (b: unknown) => api.createSaved(b),
    update: (id: string, b: unknown) => api.updateSaved(id, b),
    remove: (id: string) => api.removeSaved(id),
    runNow: (id: string) => api.runNow(id),
    runs: async () => [],
  },
}));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../hooks/useTierCapabilities', () => ({
  useTierCapabilities: () => ({ has: () => true, tier: 'pro', isLoading: false }),
}));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));

import { VideoFramesPanel } from '../../components/frames/VideoFramesPanel';
import { PasteUrlsForm } from '../../components/library/PasteUrlsForm';
import { NotesPanel } from '../../components/notes';
import { PinQuestionButton } from '../../components/savedSearches/PinQuestionButton';
import { NotesPage } from '../NotesPage';
import { SavedSearchesPage } from '../SavedSearchesPage';

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

let host: HTMLDivElement;
let root: Root;
const visualBefore = featureFlags.visualAnalysis;
const confirmBefore = window.confirm;

async function mount(node: ReactNode) {
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={['/']}>{node}</MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

/** Every failure said on screen: the error toasts, then each `role="alert"` line. */
function messages(): string[] {
  const toasts = useJobStore.getState().toasts.filter((t) => t.kind === 'error').map((t) => t.message);
  const lines = Array.from(document.querySelectorAll('[role="alert"]')).map((el) => el.textContent?.trim() ?? '');
  return [...toasts, ...lines.filter(Boolean)];
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

function refused(status: number, detail: unknown): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_REQUEST', undefined, undefined, {
    status, statusText: String(status), headers, config: { headers }, data: { detail },
  });
}

const button = (label: string) => buttonsLabelled(label)[0];
/** A button whose text starts with `label` (one with a trailing arrow). */
const buttonStarting = (label: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim().startsWith(label)) as HTMLButtonElement;
const dialog = () => document.querySelector('[role="dialog"]');

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

const editor = (label: string) => document.querySelector<HTMLTextAreaElement>(`textarea[aria-label="${label}"]`)!;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  for (const fn of Object.values(api)) fn.mockReset();
  api.extract.mockResolvedValue({ status: 'queued', document_id: 'd1' });
  api.pasteUrls.mockResolvedValue(PASTED);
  api.createNote.mockResolvedValue(note('note-c', 'Mine.'));
  api.updateNote.mockResolvedValue(NOTE_A);
  api.removeNote.mockResolvedValue({ deleted: true, deleted_at: '2026-11-09T10:00:00Z' });
  api.createSaved.mockResolvedValue(SAVED);
  api.updateSaved.mockResolvedValue(SAVED);
  api.runNow.mockResolvedValue({ status: 'queued' });
  api.removeSaved.mockResolvedValue(undefined);
  featureFlags.visualAnalysis = true;
  window.confirm = () => true;
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  featureFlags.visualAnalysis = visualBefore;
  window.confirm = confirmBefore;
});

// ---------------------------------------------------------------------------
// One message per failure
// ---------------------------------------------------------------------------

const SITES = [
  {
    name: 'capturing frames',
    open: async () => {
      await mount(<VideoFramesPanel videoId="vid1" />);
      await press('Capture key frames');
    },
    call: () => api.extract,
    fallback: 'The capture could not be started. Try again.',
  },
  {
    name: 'pasting URLs',
    open: async () => {
      await mount(<PasteUrlsForm onViewShelf={() => undefined} />);
      typeInto(document.querySelector('textarea[aria-label^="URLs to shelve"]')!, 'https://example.com/a');
      await press('Shelve 1 URL');
    },
    call: () => api.pasteUrls,
    fallback: 'The batch was rejected before any URL was processed. Try again.',
  },
  {
    name: 'adding a note in the notes panel',
    open: async () => {
      await mount(<NotesPanel targetType="document" targetId="doc-1" variant="section" />);
      await press('Add a note');
      typeInto(editor('Add a note'), 'Mine.');
      await press('Save note');
    },
    call: () => api.createNote,
    fallback: 'Could not save the note. Try again.',
  },
  {
    name: 'editing a note in the notes panel',
    open: async () => {
      await mount(<NotesPanel targetType="document" targetId="doc-1" variant="section" />);
      await press('Edit');
      await press('Save note');
    },
    call: () => api.updateNote,
    fallback: 'Could not save the note. Try again.',
  },
  {
    name: 'editing a note on the notes page',
    open: async () => {
      await mount(<NotesPage />);
      await press('Edit');
      await press('Save note');
    },
    call: () => api.updateNote,
    fallback: 'Could not save the note. Try again.',
  },
  {
    name: 'pinning a question',
    open: async () => {
      await mount(<PinQuestionButton question={SAVED.question} answerLanguage="en" />);
      await press('Pin this question');
      await press('Pin it');
    },
    call: () => api.createSaved,
    fallback: 'The question could not be pinned. Try again.',
  },
  {
    name: 'pausing a saved search',
    open: async () => {
      await mount(<SavedSearchesPage />);
      await press('Pause');
    },
    call: () => api.updateSaved,
    fallback: 'Could not save the change. Try again.',
  },
  {
    name: 'changing a saved search’s schedule',
    open: async () => {
      await mount(<SavedSearchesPage />);
      await press('Change schedule');
      await press('Save schedule');
    },
    call: () => api.updateSaved,
    fallback: 'Could not save the change. Try again.',
  },
  {
    name: 'stopping a saved search’s emails',
    open: async () => {
      await mount(<SavedSearchesPage />);
      await press('Stop emails');
    },
    call: () => api.updateSaved,
    fallback: 'Could not save the change. Try again.',
  },
  {
    name: 'running a saved search now',
    open: async () => {
      await mount(<SavedSearchesPage />);
      await press('Run now');
    },
    call: () => api.runNow,
    fallback: 'Could not start a run. Try again.',
  },
  {
    name: 'deleting a saved search',
    open: async () => {
      await mount(<SavedSearchesPage />);
      await press('Delete');
    },
    call: () => api.removeSaved,
    fallback: 'Could not delete the saved search. Try again.',
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
// Each site's own words and its own surface
// ---------------------------------------------------------------------------

describe('the frames panel', () => {
  it('names a spent monthly quota in its own words', async () => {
    api.extract.mockRejectedValueOnce(
      refused(429, { error: 'quota_exceeded', resource: 'visual_extractions', consumed: 5, limit: 5, retry_after_sec: 60, retry_at: null }),
    );
    await mount(<VideoFramesPanel videoId="vid1" />);
    await press('Capture key frames');
    expect(messages()).toEqual(["You have used this month's frame captures. They reset at the start of next month."]);
  });

  it('gives the rate limiter’s own words, which are not about the month', async () => {
    api.extract.mockRejectedValueOnce(refused(429, 'Too many requests. Please retry after the cooldown period.'));
    await mount(<VideoFramesPanel videoId="vid1" />);
    await press('Capture key frames');
    expect(messages()).toEqual(['Too many requests. Please retry after the cooldown period.']);
  });

  it('offers no second capture while one is being started', async () => {
    const request = held<unknown>();
    api.extract.mockReturnValueOnce(request.promise);
    await mount(<VideoFramesPanel videoId="vid1" />);
    await press('Capture key frames');
    expect(button('Capture key frames').disabled).toBe(true);
    await act(async () => request.fail(failures.noAnswer()));
    await flush();
    expect(messages()).toEqual(['The capture could not be started. Try again.']);
  });
});

describe('the paste form', () => {
  it('keeps “See them on the shelf” while the next batch is out, then says its failure', async () => {
    await mount(<PasteUrlsForm onViewShelf={() => undefined} />);
    const field = () => document.querySelector<HTMLTextAreaElement>('textarea[aria-label^="URLs to shelve"]')!;
    typeInto(field(), 'https://example.com/a');
    await press('Shelve 1 URL');
    expect(buttonStarting('See them on the shelf').disabled).toBe(false);
    const request = held<PasteUrlsResponse>();
    api.pasteUrls.mockReturnValueOnce(request.promise);
    typeInto(field(), 'https://example.com/b');
    await press('Shelve 1 URL');
    expect(buttonStarting('See them on the shelf').disabled).toBe(true);
    await act(async () => request.fail(failures.words()));
    await flush();
    expect(messages()).toEqual([SERVER_WORDS]);
    expect(buttonStarting('See them on the shelf').disabled).toBe(false);
  });

  it('gives a full library’s own words', async () => {
    api.pasteUrls.mockRejectedValueOnce(refused(429, { resource: 'documents', message: 'Your library is full.' }));
    await mount(<PasteUrlsForm onViewShelf={() => undefined} />);
    typeInto(document.querySelector('textarea[aria-label^="URLs to shelve"]')!, 'https://example.com/a');
    await press('Shelve 1 URL');
    expect(messages()).toEqual(['Your library is full.']);
  });
});

describe.each([
  { name: 'the notes panel', open: () => mount(<NotesPanel targetType="document" targetId="doc-1" variant="section" />) },
  { name: 'the notes page', open: () => mount(<NotesPage />) },
])('$name', (surface) => {
  it('waits for an edit in flight before another note can be edited', async () => {
    const request = held<Note>();
    api.updateNote.mockReturnValueOnce(request.promise);
    await surface.open();
    await press('Edit');
    await press('Save note');
    const edits = buttonsLabelled('Edit');
    expect(edits).toHaveLength(1);
    expect(edits[0].disabled).toBe(true);
    const add = button('Add a note');
    if (add) expect(add.disabled).toBe(true);
    expect(button('Cancel').disabled).toBe(true);
    await act(async () => request.fail(failures.noWords()));
    await flush();
    expect(messages()).toEqual(['Could not save the note. Try again.']);
    expect(buttonsLabelled('Edit')[0].disabled).toBe(false);
  });

  it('a new editor starts clean: an earlier failure stays with its own editor', async () => {
    api.updateNote.mockRejectedValueOnce(failures.words());
    await surface.open();
    await press('Edit');
    await press('Save note');
    expect(messages()).toEqual([SERVER_WORDS]);
    await press('Edit');
    expect(editor('Edit note').value).toBe(NOTE_B.body_md);
    expect(messages()).toEqual([]);
  });

  it('a note’s delete keeps its toast: it has no line of its own', async () => {
    api.removeNote.mockRejectedValueOnce(failures.words());
    await surface.open();
    await press('Delete');
    // The first note now asks "Delete this note?", and its Delete comes first.
    await press('Delete');
    expect(api.removeNote).toHaveBeenCalledWith(NOTE_A.id);
    expect(messages()).toEqual([SERVER_WORDS]);
  });
});

describe('the notes panel, folded into a row', () => {
  it('cannot fold while an edit is out, then says its failure', async () => {
    const request = held<Note>();
    api.updateNote.mockReturnValueOnce(request.promise);
    await mount(<NotesPanel targetType="document" targetId="doc-1" variant="inline" />);
    await press('▸ 2 notes');
    await press('Edit');
    await press('Save note');
    const fold = document.querySelector<HTMLButtonElement>('button[aria-expanded="true"]')!;
    expect(fold.disabled).toBe(true);
    expect(button('+ Add a note').disabled).toBe(true);
    await act(async () => request.fail(failures.words()));
    await flush();
    expect(messages()).toEqual([SERVER_WORDS]);
    expect(fold.disabled).toBe(false);
  });
});

describe('the pin dialog', () => {
  it('waits for a pin in flight, then says its failure', async () => {
    const request = held<SavedSearch>();
    api.createSaved.mockReturnValueOnce(request.promise);
    await mount(<PinQuestionButton question={SAVED.question} answerLanguage="en" />);
    await press('Pin this question');
    await press('Pin it');
    expect(button('Cancel').disabled).toBe(true);
    pressEscape();
    clickBackdrop();
    await flush();
    expect(dialog()).not.toBeNull();
    await act(async () => request.fail(failures.noWords()));
    await flush();
    expect(dialog()).not.toBeNull();
    expect(messages()).toEqual(['The question could not be pinned. Try again.']);
    pressEscape();
    await flush();
    expect(dialog()).toBeNull();
  });
});

describe('a saved search’s card', () => {
  it('each action has its own line, so one failure never hides another', async () => {
    api.updateSaved.mockRejectedValueOnce(failures.words());
    api.runNow.mockRejectedValueOnce(failures.noAnswer());
    await mount(<SavedSearchesPage />);
    await press('Pause');
    await press('Run now');
    expect(messages()).toEqual([SERVER_WORDS, 'Could not start a run. Try again.']);
  });

  it('holds its other changes and its Delete while a change is out', async () => {
    const request = held<SavedSearch>();
    api.updateSaved.mockReturnValueOnce(request.promise);
    await mount(<SavedSearchesPage />);
    await press('Pause');
    for (const label of ['Stop emails', 'Pause', 'Change schedule', 'Delete']) expect(button(label).disabled, label).toBe(true);
    expect(button('Run now').disabled).toBe(false);
    await press('Stop emails');
    expect(api.updateSaved).toHaveBeenCalledTimes(1);
    await act(async () => request.fail(failures.words()));
    await flush();
    expect(messages()).toEqual([SERVER_WORDS]);
    for (const label of ['Stop emails', 'Pause', 'Change schedule', 'Delete']) expect(button(label).disabled, label).toBe(false);
  });

  it('holds its Delete while a run-now is out, and leaves its changes free', async () => {
    const request = held<unknown>();
    api.runNow.mockReturnValueOnce(request.promise);
    const asked = vi.fn(() => true);
    window.confirm = asked;
    await mount(<SavedSearchesPage />);
    await press('Run now');
    expect(api.runNow).toHaveBeenCalledTimes(1);
    expect(button('Delete').disabled).toBe(true);
    for (const label of ['Stop emails', 'Pause', 'Change schedule']) expect(button(label).disabled, label).toBe(false);
    await press('Delete');
    expect(asked).not.toHaveBeenCalled();
    expect(api.removeSaved).not.toHaveBeenCalled();
    await act(async () => request.fail(failures.words()));
    await flush();
    expect(messages()).toEqual([SERVER_WORDS]);
    expect(button('Delete').disabled).toBe(false);
  });

  it('holds everything while it is being deleted', async () => {
    const request = held<unknown>();
    api.removeSaved.mockReturnValueOnce(request.promise);
    await mount(<SavedSearchesPage />);
    await press('Delete');
    for (const label of ['Stop emails', 'Pause', 'Change schedule', 'Run now', 'Delete']) expect(button(label).disabled, label).toBe(true);
    await act(async () => request.fail(failures.noWords()));
    await flush();
    expect(messages()).toEqual(['Could not delete the saved search. Try again.']);
  });
});
