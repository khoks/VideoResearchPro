/**
 * T-3.4.1.17: one toast per failure on the shares inbox and the importer, under
 * the app's own query client. Each action toasted from the page's `mutate` call
 * and again from the global handler; now its hook says it, in the server's words
 * or the page's sentence, sets `meta.errorsShownHere`, and says nothing of a 401.
 * An import can run for minutes, so its failure must still be said once the
 * reader has left the page, which a per-call `onError` cannot do.
 *
 * Mutation checks, run on 2026-11-09: `meta` off the nine hooks fails every
 * failure row but `sessionEnded` with two toasts; `usePreviewImport` reading one
 * sentence for both cases fails "re-reading the dates" with the other sentence;
 * the toast moved back onto the page's `mutate` fails "once the reader has left".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { EchoImportItem, ImportPreview, Share } from '../../services/echoApi';
import { createQueryClient } from '../../services/queryClient';
import {
  FAILURE_KINDS,
  clearToasts,
  expectedToasts,
  failures,
  flush,
  press,
  toastMessages,
} from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const share = (over: Partial<Share>): Share => ({
  id: 's1',
  received_at: '2026-11-04T09:00:00Z',
  updated_at: '2026-11-04T09:00:00Z',
  surface: 'manual_quick_share',
  content_type: 'text_snippet',
  kind: 'text',
  url: null,
  text: 'Some words',
  file: null,
  user_annotation: null,
  author_is_tenant: false,
  processing_state: 'processed',
  linked_document_id: null,
  ...over,
});
const FAILED_TEXT = share({ id: 's1', processing_state: 'failed', processing: { error: 'Could not read it.' } });
const PAGE_LINK = share({
  id: 's2', kind: 'url', content_type: 'url', url: 'https://example.com/a', text: null,
  processing: { title: 'A page', library_offer: { eligible: true } },
});

const KEEP: ImportPreview = {
  importer: 'google_keep', label: 'Google Keep', summary: { notes: 3 }, participants: [], options: {}, warnings: [],
};
const CHAT: ImportPreview = {
  importer: 'whatsapp', label: 'WhatsApp chat', summary: { messages: 10, turns: 4, media: 0, date_order_inferred: false },
  participants: [{ name: 'Asha', messages: 5 }, { name: 'Sam', messages: 5 }], options: {}, warnings: [],
};
const FAILED_IMPORT: EchoImportItem = {
  id: 'i1', importer: 'google_keep', filename: 'takeout.zip', status: 'failed', options: {}, counts: { shares: 3 },
  summary: {}, error: 'Indexing stopped.', created_at: '2026-11-04T09:00:00Z', finished_at: null,
};

const api = {
  listShares: vi.fn(async () => ({ items: [FAILED_TEXT, PAGE_LINK], total: 2 })),
  listImports: vi.fn(async () => ({ items: [FAILED_IMPORT] })),
  updateShare: vi.fn<(id: string, p: unknown) => Promise<Share>>(),
  reprocessShare: vi.fn<(id: string) => Promise<Share>>(),
  addShareToLibrary: vi.fn<(id: string) => Promise<unknown>>(),
  deleteShare: vi.fn<(id: string) => Promise<void>>(),
  previewImport: vi.fn<(file: File, options?: unknown) => Promise<ImportPreview>>(),
  runImport: vi.fn<(file: File, options?: unknown) => Promise<EchoImportItem>>(),
  retryImportEmbedding: vi.fn<(id: string) => Promise<EchoImportItem>>(),
  deleteImport: vi.fn<(id: string) => Promise<{ shares: number }>>(),
};
vi.mock('../../services/echoApi', () => ({
  echoApi: {
    sharesSeen: async () => undefined,
    listShares: () => api.listShares(),
    listImports: () => api.listImports(),
    updateShare: (id: string, p: unknown) => api.updateShare(id, p),
    reprocessShare: (id: string) => api.reprocessShare(id),
    addShareToLibrary: (id: string) => api.addShareToLibrary(id),
    deleteShare: (id: string) => api.deleteShare(id),
    previewImport: (file: File, options?: unknown) => api.previewImport(file, options),
    runImport: (file: File, options?: unknown) => api.runImport(file, options),
    retryImportEmbedding: (id: string) => api.retryImportEmbedding(id),
    deleteImport: (id: string) => api.deleteImport(id),
  },
}));
vi.mock('../../hooks/useTierCapabilities', () => ({
  useTierCapabilities: () => ({ has: () => true, tier: 'studio', isLoading: false }),
}));
vi.mock('../../components/echo/QuickShare', () => ({ QuickShare: () => null }));

import { EchoImportPage } from '../EchoImportPage';
import { EchoInboxPage } from '../EchoInboxPage';

let host: HTMLDivElement;
let root: Root;
const EXPORT = new File(['{}'], 'takeout.zip', { type: 'application/zip' });

async function mount(page: 'inbox' | 'import') {
  // The importer previews a file handed over in router state at once, as the drop zone does.
  const entry = page === 'inbox' ? '/echo/inbox' : { pathname: '/echo/import', state: { file: EXPORT } };
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={[entry]}>{page === 'inbox' ? <EchoInboxPage /> : <EchoImportPage />}</MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

function chooseDateOrder(value: 'dmy' | 'mdy') {
  const el = document.querySelector('select[aria-label="Date order"]') as HTMLSelectElement;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!.call(el, value);
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  for (const fn of Object.values(api)) fn.mockClear();
  api.updateShare.mockReset().mockResolvedValue(FAILED_TEXT);
  api.reprocessShare.mockReset().mockResolvedValue(FAILED_TEXT);
  api.addShareToLibrary.mockReset().mockResolvedValue({});
  api.deleteShare.mockReset().mockResolvedValue(undefined);
  api.previewImport.mockReset().mockResolvedValue(KEEP);
  api.runImport.mockReset().mockResolvedValue({ ...FAILED_IMPORT, id: 'i2', status: 'embedding' });
  api.retryImportEmbedding.mockReset().mockResolvedValue(FAILED_IMPORT);
  api.deleteImport.mockReset().mockResolvedValue({ shares: 3 });
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const SITES = [
  {
    name: 'the inbox: deleting a share',
    page: 'inbox' as const,
    call: () => api.deleteShare,
    go: async () => {
      await press('Delete');
      await press('Delete', 'last');
    },
    fallback: 'Delete failed. The share may already be gone.',
  },
  {
    name: 'the inbox: saving a share',
    page: 'inbox' as const,
    call: () => api.updateShare,
    go: () => press('These are my words'),
    fallback: 'Could not save.',
  },
  {
    name: 'the inbox: retrying a failed share',
    page: 'inbox' as const,
    call: () => api.reprocessShare,
    go: () => press('Retry'),
    fallback: 'Could not queue the retry.',
  },
  {
    name: 'the inbox: adding a page to the library',
    page: 'inbox' as const,
    call: () => api.addShareToLibrary,
    go: () => press('Add to library'),
    fallback: 'Could not add it to the library.',
  },
  {
    name: 'the importer: reading a file',
    page: 'import' as const,
    call: () => api.previewImport,
    // The file is handed over on mount; the failure is set up before it.
    go: async () => undefined,
    fallback: 'This file could not be read.',
  },
  {
    name: 'the importer: importing',
    page: 'import' as const,
    call: () => api.runImport,
    go: () => press('Import'),
    fallback: 'The import failed.',
  },
  {
    name: 'the importer: retrying the indexing',
    page: 'import' as const,
    call: () => api.retryImportEmbedding,
    go: () => press('Retry indexing'),
    fallback: 'Could not retry.',
  },
  {
    name: 'the importer: undoing an import',
    page: 'import' as const,
    call: () => api.deleteImport,
    go: async () => {
      await press('Undo import');
      await press('Undo import', 'last');
    },
    fallback: 'Undo failed.',
  },
];

describe.each(SITES)('$name', (site) => {
  it.each(FAILURE_KINDS)('says a failure (%s) once', async (kind) => {
    site.call().mockRejectedValueOnce(failures[kind]());
    await mount(site.page);
    await site.go();
    expect(site.call()).toHaveBeenCalledTimes(1);
    expect(toastMessages()).toEqual(expectedToasts(kind, site.fallback));
  });
});

describe('the importer', () => {
  it.each(FAILURE_KINDS)('says a failure (%s) re-reading the dates once, in its own words', async (kind) => {
    api.previewImport.mockResolvedValueOnce(CHAT).mockRejectedValueOnce(failures[kind]());
    await mount('import');
    chooseDateOrder('mdy');
    await flush();
    expect(api.previewImport).toHaveBeenCalledTimes(2);
    expect(toastMessages()).toEqual(expectedToasts(kind, 'Could not re-read the dates.'));
  });

  it('still says a failed import once the reader has left the page', async () => {
    let fail: (reason: unknown) => void = () => undefined;
    api.runImport.mockReturnValueOnce(new Promise((_, reject) => (fail = reject)));
    await mount('import');
    await press('Import');
    act(() => root.unmount());
    await act(async () => fail(failures.noAnswer()));
    await flush();
    expect(toastMessages()).toEqual(['The import failed.']);
    root = createRoot(host);
  });
});
