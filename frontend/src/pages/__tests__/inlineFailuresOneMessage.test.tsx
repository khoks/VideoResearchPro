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
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Tag } from '../../services/tagsApi';
import type { JobTemplate } from '../../services/jobTemplatesApi';
import { createQueryClient } from '../../services/queryClient';
import {
  FAILURE_KINDS,
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
