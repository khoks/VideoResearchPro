/**
 * T-3.4.1.18: a failure said where the reader acted is said there alone, under
 * the app's own query client. The tags manager (save, merge, delete), the
 * delete-shelf modal and a template's delete each showed a line on the page and
 * the global toast beside it. Now the hook sets `meta: ERRORS_SHOWN_HERE`, the
 * line stays, and a 401 says nothing at all: the session-expiry path owns it.
 *
 * "A message" here is a toast or a line with `role="alert"`, so a test fails on
 * two of either kind, or one of each.
 *
 * Mutation checks, run on 2026-11-09: taking `meta` off `useUpdateTag` fails the
 * tag save's `words`, `noWords` and `noAnswer` rows with the line and a toast;
 * off `useDeleteTag`, the merge and delete rows; off `useDeleteShelf` or
 * `useDeleteTemplate`, their rows. Each also fails the second guard in
 * `oneToastPerFailure.test.ts`. `inlineErrorMessage` without its 401 check fails
 * every `sessionEnded` row here, with "Not authenticated" on the page.
 */
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Tag } from '../../services/tagsApi';
import type { JobTemplate } from '../../services/jobTemplatesApi';
import { createQueryClient } from '../../services/queryClient';
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

const ALPHA: Tag = { id: 'tag-a', name: 'Alpha', color: 'default', document_count: 2, created_at: '2026-11-01T09:00:00Z' };
const BETA: Tag = { id: 'tag-b', name: 'Beta', color: 'default', document_count: 1, created_at: '2026-11-01T09:00:00Z' };

const TEMPLATE: JobTemplate = {
  id: 'tpl-1',
  name: 'Weekly tariffs',
  description: null,
  job_type: 'topic',
  builtin: false,
  builtin_key: null,
  version: 1,
  parameters: {
    job_type: 'topic',
    num_videos: 10,
    channel_list: null,
  } as unknown as JobTemplate['parameters'],
  problems: [],
  created_at: '2026-11-01T09:00:00Z',
  updated_at: '2026-11-01T09:00:00Z',
};

const api = {
  listTags: vi.fn(async () => [ALPHA, BETA]),
  updateTag: vi.fn<(id: string, body: unknown) => Promise<Tag>>(),
  removeTag: vi.fn<(id: string, into?: string) => Promise<void>>(),
  removeShelf: vi.fn<(id: string) => Promise<void>>(),
  listTemplates: vi.fn(async () => [TEMPLATE]),
  removeTemplate: vi.fn<(id: string) => Promise<void>>(),
};
vi.mock('../../services/tagsApi', () => ({
  tagsApi: {
    list: () => api.listTags(),
    update: (id: string, body: unknown) => api.updateTag(id, body),
    remove: (id: string, into?: string) => api.removeTag(id, into),
  },
}));
vi.mock('../../services/shelvesApi', () => ({
  shelvesApi: { remove: (id: string) => api.removeShelf(id) },
}));
vi.mock('../../services/jobTemplatesApi', () => ({
  jobTemplatesApi: {
    list: () => api.listTemplates(),
    remove: (id: string) => api.removeTemplate(id),
    versions: async () => [],
  },
}));

import { TagsManagerModal } from '../../components/tags/TagsManagerModal';
import { DeleteShelfModal } from '../../components/shelves/DeleteShelfModal';
import { TemplatesPage } from '../TemplatesPage';

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

/** Every message on screen: the toasts, then each line with `role="alert"`. */
function messages(): string[] {
  const lines = Array.from(document.querySelectorAll('[role="alert"]')).map((el) => el.textContent?.trim() ?? '');
  return [...toastMessages(), ...lines];
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  for (const fn of Object.values(api)) fn.mockClear();
  api.updateTag.mockReset().mockResolvedValue(ALPHA);
  api.removeTag.mockReset().mockResolvedValue(undefined);
  api.removeShelf.mockReset().mockResolvedValue(undefined);
  api.removeTemplate.mockReset().mockResolvedValue(undefined);
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function chooseMergeTarget(id: string) {
  const select = document.querySelector('select[aria-label="Merge Alpha into"]') as HTMLSelectElement;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!.call(select, id);
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

const SITES = [
  {
    name: 'saving a tag',
    node: () => <TagsManagerModal open onClose={() => undefined} />,
    call: () => api.updateTag,
    go: async () => {
      await press('Edit');
      typeInto(document.querySelector('input[aria-label="New name for Alpha"]') as HTMLInputElement, 'Alpha two');
      await press('Save');
    },
    fallback: 'Could not save the tag.',
  },
  {
    name: 'merging a tag',
    node: () => <TagsManagerModal open onClose={() => undefined} />,
    call: () => api.removeTag,
    go: async () => {
      await press('Edit');
      chooseMergeTarget(BETA.id);
      await press('Merge');
    },
    fallback: 'Could not merge the tag.',
  },
  {
    name: 'deleting a tag',
    node: () => <TagsManagerModal open onClose={() => undefined} />,
    call: () => api.removeTag,
    go: async () => {
      await press('Edit');
      await press('Delete…');
      await press('Delete tag');
    },
    fallback: 'Could not delete the tag.',
  },
  {
    name: 'deleting a shelf',
    node: () => <DeleteShelfModal shelf={{ id: 'shelf-1', name: 'Trade', job_count: 2 }} onClose={() => undefined} />,
    call: () => api.removeShelf,
    go: () => press('Delete shelf'),
    fallback: 'Could not delete the shelf.',
  },
  {
    name: 'deleting a template',
    node: () => <TemplatesPage />,
    call: () => api.removeTemplate,
    go: async () => {
      await press('Delete…');
      await press('Delete');
    },
    fallback: 'Could not delete the template.',
  },
];

describe.each(SITES)('$name', (site) => {
  it.each(FAILURE_KINDS)('says a failure (%s) once, on the page', async (kind) => {
    site.call().mockRejectedValueOnce(failures[kind]());
    await mount(site.node());
    await site.go();
    expect(site.call()).toHaveBeenCalledTimes(1);
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(expectedToasts(kind, site.fallback));
  });

  it('says nothing when it goes through', async () => {
    await mount(site.node());
    await site.go();
    expect(site.call()).toHaveBeenCalledTimes(1);
    expect(messages()).toEqual([]);
  });
});

describe('merging a tag', () => {
  it('sends the tag it folds into', async () => {
    await mount(<TagsManagerModal open onClose={() => undefined} />);
    await press('Edit');
    chooseMergeTarget(BETA.id);
    await press('Merge');
    expect(api.removeTag).toHaveBeenCalledWith(ALPHA.id, BETA.id);
  });
});

// ---------------------------------------------------------------------------
// Closing before the answer
// ---------------------------------------------------------------------------
//
// With the global toast standing aside, the modal's line is the only word on a
// failure. Closed before the answer, the line would go with it (the tags
// manager unmounts its rows) or sit hidden (the shelf pages keep the modal
// mounted), and the failure would be said nowhere. So each waits for the answer:
// Escape, the backdrop and Close do nothing while the request is in flight.
//
// Mutation checks, run on 2026-11-09: letting `DeleteShelfModal`'s `dismiss`
// close while the delete is pending fails "waits for a pending delete" with no
// dialog and no message; taking out its reset fails "shows no line from an
// earlier opening" with the stale line under Energy's name; letting the tags
// manager's `dismiss` close while busy, or dropping `mutationKey` from
// `useUpdateTag` or `useDeleteTag`, fails "waits for a pending save" or "waits
// for a pending delete" with no dialog and no message.

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

const dialogOpen = () => !!document.querySelector('[role="dialog"]');

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

/** Both shelf pages keep the modal mounted and change only `shelf`. */
const TRADE = { id: 'shelf-1', name: 'Trade', job_count: 2 };
const ENERGY = { id: 'shelf-2', name: 'Energy', job_count: 0 };

function ShelvesHost() {
  const [shelf, setShelf] = useState<typeof TRADE | null>(TRADE);
  return (
    <>
      <button type="button" onClick={() => setShelf(TRADE)}>
        Open Trade
      </button>
      <button type="button" onClick={() => setShelf(ENERGY)}>
        Open Energy
      </button>
      <DeleteShelfModal shelf={shelf} onClose={() => setShelf(null)} />
    </>
  );
}

function TagsHost() {
  const [open, setOpen] = useState(true);
  return <TagsManagerModal open={open} onClose={() => setOpen(false)} />;
}

describe('the delete-shelf modal', () => {
  it('waits for a pending delete, then says its failure', async () => {
    const request = held<void>();
    api.removeShelf.mockReturnValueOnce(request.promise);
    await mount(<ShelvesHost />);
    await press('Delete shelf');
    pressEscape();
    clickBackdrop();
    await flush();
    expect(dialogOpen()).toBe(true);
    await act(async () => request.fail(failures.noWords()));
    await flush();
    expect(dialogOpen()).toBe(true);
    expect(messages()).toEqual(['Could not delete the shelf.']);
  });

  it('closes on Escape once the answer is in', async () => {
    api.removeShelf.mockRejectedValueOnce(failures.noWords());
    await mount(<ShelvesHost />);
    await press('Delete shelf');
    pressEscape();
    await flush();
    expect(dialogOpen()).toBe(false);
  });

  it('shows no line from an earlier opening', async () => {
    api.removeShelf.mockRejectedValueOnce(failures.noWords());
    await mount(<ShelvesHost />);
    await press('Delete shelf');
    expect(messages()).toEqual(['Could not delete the shelf.']);
    await press('Keep it');
    expect(dialogOpen()).toBe(false);
    await press('Open Energy');
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Energy');
    expect(messages()).toEqual([]);
    await press('Keep it');
    await press('Open Trade');
    expect(messages()).toEqual([]);
  });
});

describe('the tags manager', () => {
  it('waits for a pending save, then says its failure on the row', async () => {
    const request = held<Tag>();
    api.updateTag.mockReturnValueOnce(request.promise);
    await mount(<TagsHost />);
    await press('Edit');
    typeInto(document.querySelector('input[aria-label="New name for Alpha"]') as HTMLInputElement, 'Beta');
    await press('Save');
    pressEscape();
    clickBackdrop();
    await press('Close');
    expect(dialogOpen()).toBe(true);
    await act(async () => request.fail(failures.words()));
    await flush();
    expect(dialogOpen()).toBe(true);
    expect(messages()).toEqual([SERVER_WORDS]);
    await press('Close');
    expect(dialogOpen()).toBe(false);
  });

  it('waits for a pending delete, then says its failure on the row', async () => {
    const request = held<void>();
    api.removeTag.mockReturnValueOnce(request.promise);
    await mount(<TagsHost />);
    await press('Edit');
    await press('Delete…');
    await press('Delete tag');
    pressEscape();
    await press('Close');
    expect(dialogOpen()).toBe(true);
    await act(async () => request.fail(failures.noAnswer()));
    await flush();
    expect(messages()).toEqual(['Could not delete the tag.']);
  });
});
