/**
 * T-3.4.1.22 at the two label pickers, under the app's own query client: "Add to
 * shelf" on a run and the tag control on a source. `LabelPicker` awaits the
 * `onToggle` and `onCreate` its caller hands it and says a rejection in the
 * popover; the mutations behind them did not set `meta`, so the global toast
 * said the failure again. Now `useAddJobToShelf`, `useCreateShelf`,
 * `useApplyTag`, `useUnapplyTag` and `useCreateTag` set it (every caller shows a
 * line), `useRemoveJobFromShelf` takes `{ inlineErrors }` (the picker passes it;
 * a shelf page's own Remove keeps the toast), and a 401 says nothing. While a
 * change is in flight the popover stays open: a click outside, Escape and the
 * button wait, since closing it would hide the line before it is written.
 *
 * "A message" here is an error toast or a line with `role="alert"`.
 *
 * Mutation checks, run on 2026-11-09: taking `meta` off `useCreateShelf` or
 * `useApplyTag`, or `{ inlineErrors: true }` off the picker's
 * `useRemoveJobFromShelf`, fails that action's `words`, `noWords` and
 * `noAnswer` rows with the line and a toast; `apiErrorMessage` back in
 * `LabelPicker`'s toggle line fails the four toggle rows' `sessionEnded` with
 * "Not authenticated"; and the outside click, Escape or the button closing the
 * popover while `pending` fails both "waits for a change in flight".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Shelf } from '../../../services/shelvesApi';
import type { Tag, TagSummary } from '../../../services/tagsApi';
import { createQueryClient } from '../../../services/queryClient';
import { useJobStore } from '../../../stores/jobStore';
import {
  FAILURE_KINDS,
  clearToasts,
  expectedToasts,
  failures,
  flush,
  toastMessages,
  typeInto,
} from '../../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function shelf(id: string, name: string, jobIds: string[]): Shelf {
  return {
    id,
    name,
    description: null,
    color: 'default',
    job_count: jobIds.length,
    job_ids: jobIds,
    created_at: '2026-11-01T09:00:00Z',
    updated_at: '2026-11-01T09:00:00Z',
  };
}

const TRADE = shelf('shelf-1', 'Trade', ['job-1']);
const ENERGY = shelf('shelf-2', 'Energy', []);
const ALPHA: Tag = { id: 'tag-a', name: 'Alpha', color: 'default', document_count: 1, created_at: '2026-11-01T09:00:00Z' };
const BETA: Tag = { id: 'tag-b', name: 'Beta', color: 'default', document_count: 0, created_at: '2026-11-01T09:00:00Z' };

const api = {
  addJob: vi.fn<(id: string, jobId: string) => Promise<Shelf>>(),
  removeJob: vi.fn<(id: string, jobId: string) => Promise<void>>(),
  createShelf: vi.fn<(body: unknown) => Promise<Shelf>>(),
  apply: vi.fn<(documentId: string, tagId: string) => Promise<void>>(),
  unapply: vi.fn<(documentId: string, tagId: string) => Promise<void>>(),
  createTag: vi.fn<(body: unknown) => Promise<Tag>>(),
};

vi.mock('../../../services/shelvesApi', async (orig) => ({
  ...(await orig<typeof import('../../../services/shelvesApi')>()),
  shelvesApi: {
    list: async () => [TRADE, ENERGY],
    addJob: (id: string, jobId: string) => api.addJob(id, jobId),
    removeJob: (id: string, jobId: string) => api.removeJob(id, jobId),
    create: (body: unknown) => api.createShelf(body),
  },
}));
vi.mock('../../../services/tagsApi', () => ({
  tagsApi: {
    list: async () => [ALPHA, BETA],
    apply: (documentId: string, tagId: string) => api.apply(documentId, tagId),
    unapply: (documentId: string, tagId: string) => api.unapply(documentId, tagId),
    create: (body: unknown) => api.createTag(body),
  },
}));
vi.mock('../../../hooks/useTierCapabilities', () => ({ useTierCapabilities: () => ({ has: () => true }) }));

import { ShelfPicker } from '../../shelves/ShelfPicker';
import { DocumentTags } from '../../tags/DocumentTags';

let host: HTMLDivElement;
let root: Root;

async function mount(node: React.ReactNode) {
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter>{node}</MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const shelfPicker = () => mount(<ShelfPicker jobId="job-1" />);
const tagPicker = () => mount(<DocumentTags documentId="doc-1" tags={[ALPHA as TagSummary]} />);

/** Every failure said on screen: the error toasts, then each line with `role="alert"`. */
function messages(): string[] {
  const toasts = useJobStore.getState().toasts.filter((t) => t.kind === 'error').map((t) => t.message);
  const lines = Array.from(document.querySelectorAll('[role="alert"]')).map((el) => el.textContent?.trim() ?? '');
  return [...toasts, ...lines];
}

const popover = () => document.querySelector('[role="dialog"]');

async function openPicker() {
  const b = host.querySelector('button[aria-haspopup="dialog"]') as HTMLButtonElement;
  await act(async () => b.click());
  await flush();
}

async function toggle(name: string) {
  const label = Array.from(popover()!.querySelectorAll('label')).find((l) => l.textContent?.includes(name));
  const box = label!.querySelector('input[type="checkbox"]') as HTMLInputElement;
  await act(async () => box.click());
  await flush();
}

async function create(name: string) {
  typeInto(popover()!.querySelector('input:not([type="checkbox"])') as HTMLInputElement, name);
  const b = Array.from(popover()!.querySelectorAll('button')).find((el) => el.textContent?.trim() === 'Create');
  await act(async () => b!.click());
  await flush();
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
  api.addJob.mockResolvedValue(ENERGY);
  api.removeJob.mockResolvedValue(undefined);
  api.createShelf.mockResolvedValue(shelf('shelf-3', 'Ports', []));
  api.apply.mockResolvedValue(undefined);
  api.unapply.mockResolvedValue(undefined);
  api.createTag.mockResolvedValue({ ...BETA, id: 'tag-c', name: 'Gamma' });
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const SITES = [
  { name: 'adding a run to a shelf', open: shelfPicker, go: () => toggle('Energy'), call: () => api.addJob, fallback: 'Could not save that change.' },
  { name: 'taking a run off a shelf', open: shelfPicker, go: () => toggle('Trade'), call: () => api.removeJob, fallback: 'Could not save that change.' },
  { name: 'a new shelf from the picker', open: shelfPicker, go: () => create('Ports'), call: () => api.createShelf, fallback: 'Could not create it.' },
  { name: 'tagging a source', open: tagPicker, go: () => toggle('Beta'), call: () => api.apply, fallback: 'Could not save that change.' },
  { name: 'untagging a source', open: tagPicker, go: () => toggle('Alpha'), call: () => api.unapply, fallback: 'Could not save that change.' },
  { name: 'a new tag from the picker', open: tagPicker, go: () => create('Gamma'), call: () => api.createTag, fallback: 'Could not create it.' },
];

describe.each(SITES)('$name', (site) => {
  it.each(FAILURE_KINDS)('says a failure (%s) once, in the picker', async (kind) => {
    site.call().mockRejectedValueOnce(failures[kind]());
    await site.open();
    await openPicker();
    await site.go();
    expect(site.call()).toHaveBeenCalledTimes(1);
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(expectedToasts(kind, site.fallback));
  });

  it('says nothing when it goes through', async () => {
    await site.open();
    await openPicker();
    await site.go();
    expect(site.call()).toHaveBeenCalledTimes(1);
    expect(messages()).toEqual([]);
  });
});

describe.each([
  { name: 'the shelf picker', open: shelfPicker, go: () => toggle('Energy'), call: () => api.addJob as ReturnType<typeof vi.fn> },
  { name: 'the tag picker', open: tagPicker, go: () => create('Gamma'), call: () => api.createTag as ReturnType<typeof vi.fn> },
])('$name', (site) => {
  it('waits for a change in flight: a click outside, Escape and its button leave it open', async () => {
    const request = held<never>();
    site.call().mockReturnValueOnce(request.promise);
    await site.open();
    await openPicker();
    await site.go();
    act(() => {
      document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(popover()).not.toBeNull();
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(popover()).not.toBeNull();
    // Its button would close it; it waits too.
    await openPicker();
    expect(popover()).not.toBeNull();
    await act(async () => request.fail(failures.noAnswer()));
    await flush();
    expect(popover()).not.toBeNull();
    expect(messages()).toHaveLength(1);
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    await flush();
    expect(popover()).toBeNull();
  });
});
