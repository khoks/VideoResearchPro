/**
 * T-3.4.1.17: one toast per failure on the Echo page's cards and the drop zone,
 * under the app's own query client. Deleting everything, making or revoking a
 * share token, and dropping a file, a link or some text each toasted from the
 * component's `mutate` call and again from the global handler. Now the hook says
 * it, in the server's words or the component's sentence, sets
 * `meta.errorsShownHere`, and says nothing of a 401.
 *
 * The drop zone shows why the hook is the place: a per-call `onError` runs for
 * the last `mutate` of an observer only, so of two dropped files that both failed
 * only the second was named. Quick share, the hooks' other caller, keeps its own
 * line in its dialog and the global toast (`toastErrors` off).
 *
 * Mutation checks, run on 2026-11-09: `meta` off the hooks fails every failure
 * row but `sessionEnded` with two toasts; `toastErrors` left off in the drop zone
 * fails its `noWords` and `noAnswer` rows, in axios's words, and "names each of
 * two dropped files"; the data card's toast moved back onto its `mutate` call
 * fails "once the reader has left".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { EchoFootprint, ShareToken } from '../../../services/echoApi';
import { createQueryClient } from '../../../services/queryClient';
import {
  FAILURE_KINDS,
  clearToasts,
  expectedToasts,
  failures,
  flush,
  press,
  toastMessages,
  typeInto,
} from '../../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const FOOTPRINT: EchoFootprint = { rows: { personal_context: 3 }, files: 1, vectors: { shares_global: 2 } };
const EMPTY: EchoFootprint = { rows: { personal_context: 0 }, files: 0, vectors: { shares_global: 0 } };
const TOKEN: ShareToken = { id: 't1', label: 'Chrome', prefix: 'pdv_ab', created_at: '2026-11-01T09:00:00Z', last_used_at: null };

const api = {
  footprint: vi.fn(async () => FOOTPRINT),
  deleteBrain: vi.fn<() => Promise<{ footprint_after: EchoFootprint }>>(),
  listShareTokens: vi.fn(async () => ({ items: [TOKEN], max: 10 })),
  createShareToken: vi.fn<(label: string) => Promise<ShareToken & { token: string }>>(),
  revokeShareToken: vi.fn<(id: string) => Promise<void>>(),
  uploadShare: vi.fn<(file: File, fields?: unknown) => Promise<unknown>>(),
  createShare: vi.fn<(payload: unknown) => Promise<unknown>>(),
};
vi.mock('../../../services/echoApi', () => ({
  echoApi: {
    footprint: () => api.footprint(),
    deleteBrain: () => api.deleteBrain(),
    listShareTokens: () => api.listShareTokens(),
    createShareToken: (label: string) => api.createShareToken(label),
    revokeShareToken: (id: string) => api.revokeShareToken(id),
    uploadShare: (file: File, fields?: unknown) => api.uploadShare(file, fields),
    createShare: (payload: unknown) => api.createShare(payload),
  },
}));
vi.mock('../../../services/api', () => ({ default: { defaults: { baseURL: 'https://app.example/api/v1' } } }));

import { EchoDataCard } from '../EchoDataCard';
import { EchoDropZone } from '../EchoDropZone';
import { ShareTokensCard } from '../ShareTokensCard';

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

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  for (const fn of Object.values(api)) fn.mockClear();
  api.deleteBrain.mockReset().mockResolvedValue({ footprint_after: EMPTY });
  api.createShareToken.mockReset().mockResolvedValue({ ...TOKEN, id: 't2', token: 'pdv_secret' });
  api.revokeShareToken.mockReset().mockResolvedValue(undefined);
  api.uploadShare.mockReset().mockResolvedValue({});
  api.createShare.mockReset().mockResolvedValue({});
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function deleteEverything() {
  await press('Delete everything Echo knows');
  typeInto(document.querySelector('input[aria-label="Type DELETE to confirm"]') as HTMLInputElement, 'DELETE');
  await press('Delete permanently');
}

function drop(data: { files?: File[]; types: string[]; text?: Record<string, string> }) {
  const e = new Event('drop', { bubbles: true, cancelable: true });
  Object.defineProperty(e, 'dataTransfer', {
    value: { types: data.types, files: data.files ?? [], getData: (t: string) => data.text?.[t] ?? '' },
  });
  act(() => {
    window.dispatchEvent(e);
  });
}

const SITES = [
  {
    name: 'deleting everything',
    node: () => <EchoDataCard />,
    call: () => api.deleteBrain,
    go: deleteEverything,
    fallback: 'Delete failed. Nothing past the failing store was removed; try again.',
  },
  {
    name: 'making a share token',
    node: () => <ShareTokensCard />,
    call: () => api.createShareToken,
    go: () => press('Make a share token'),
    fallback: 'Could not make a token.',
  },
  {
    name: 'revoking a share token',
    node: () => <ShareTokensCard />,
    call: () => api.revokeShareToken,
    go: () => press('Revoke'),
    fallback: 'Could not revoke it.',
  },
  {
    name: 'dropping a file',
    node: () => <EchoDropZone />,
    call: () => api.uploadShare,
    go: async () => {
      drop({ types: ['Files'], files: [new File(['x'], 'notes.pdf', { type: 'application/pdf' })] });
      await flush();
    },
    fallback: 'Could not add notes.pdf.',
  },
  {
    name: 'dropping a link',
    node: () => <EchoDropZone />,
    call: () => api.createShare,
    go: async () => {
      drop({ types: ['text/uri-list'], text: { 'text/uri-list': 'https://example.com/a' } });
      await flush();
    },
    fallback: 'Could not add the link.',
  },
  {
    name: 'dropping some text',
    node: () => <EchoDropZone />,
    call: () => api.createShare,
    go: async () => {
      drop({ types: ['text/plain'], text: { 'text/plain': 'A thought worth keeping, in a few words.' } });
      await flush();
    },
    fallback: 'Could not add the text.',
  },
];

describe.each(SITES)('$name', (site) => {
  it.each(FAILURE_KINDS)('says a failure (%s) once', async (kind) => {
    site.call().mockRejectedValueOnce(failures[kind]());
    await mount(site.node());
    await site.go();
    expect(site.call()).toHaveBeenCalledTimes(1);
    expect(toastMessages()).toEqual(expectedToasts(kind, site.fallback));
  });
});

describe('the drop zone', () => {
  it('names each of two dropped files that failed, once each', async () => {
    api.uploadShare.mockRejectedValueOnce(failures.noWords()).mockRejectedValueOnce(failures.noAnswer());
    await mount(<EchoDropZone />);
    drop({
      types: ['Files'],
      files: [new File(['x'], 'one.pdf', { type: 'application/pdf' }), new File(['y'], 'two.pdf', { type: 'application/pdf' })],
    });
    await flush();
    expect(api.uploadShare).toHaveBeenCalledTimes(2);
    expect(toastMessages().sort()).toEqual(['Could not add one.pdf.', 'Could not add two.pdf.']);
  });
});

// T-3.4.1.19: every file of a drop that landed is said, in the drop zone's own
// words, one toast each. A per-call `onSuccess` runs for an observer's last
// `mutate` only, so of several files only the last was named. Mutation checks,
// run on 2026-11-09: putting back the per-call `onSuccess` on `upload.mutate`
// fails "names each of three dropped files" (the mixed drop still passes, its
// last file being the one that landed); on `create.mutate`, "says a link and
// some text dropped one after the other"; taking out the `mounted` check fails
// "says nothing once the zone has gone".
describe('the drop zone, when files land', () => {
  const pdf = (name: string) => new File(['x'], name, { type: 'application/pdf' });

  it('names each of three dropped files, once each', async () => {
    await mount(<EchoDropZone />);
    drop({ types: ['Files'], files: [pdf('one.pdf'), pdf('two.pdf'), pdf('three.pdf')] });
    await flush();
    expect(api.uploadShare).toHaveBeenCalledTimes(3);
    expect(toastMessages()).toEqual(['Added one.pdf to Echo.', 'Added two.pdf to Echo.', 'Added three.pdf to Echo.']);
  });

  it('says the file that landed and the one that failed, one message each', async () => {
    api.uploadShare.mockReset().mockImplementation(async (file: File) => {
      if (file.name === 'one.pdf') throw failures.noWords();
      return {};
    });
    await mount(<EchoDropZone />);
    drop({ types: ['Files'], files: [pdf('one.pdf'), pdf('two.pdf')] });
    await flush();
    expect(toastMessages().sort()).toEqual(['Added two.pdf to Echo.', 'Could not add one.pdf.']);
  });

  it('says a link and some text dropped one after the other', async () => {
    let landLink: (v: unknown) => void = () => undefined;
    api.createShare.mockReset().mockReturnValueOnce(new Promise((r) => (landLink = r))).mockResolvedValueOnce({});
    await mount(<EchoDropZone />);
    drop({ types: ['text/uri-list'], text: { 'text/uri-list': 'https://example.com/a' } });
    drop({ types: ['text/plain'], text: { 'text/plain': 'A thought worth keeping, in a few words.' } });
    await flush();
    await act(async () => landLink({}));
    await flush();
    expect(toastMessages().sort()).toEqual(['Link added to Echo.', 'Text added to Echo.']);
  });

  it('says nothing once the zone has gone with the session', async () => {
    let land: (v: unknown) => void = () => undefined;
    api.uploadShare.mockReset().mockReturnValueOnce(new Promise((r) => (land = r)));
    await mount(<EchoDropZone />);
    drop({ types: ['Files'], files: [pdf('private.pdf')] });
    await flush();
    act(() => root.unmount());
    await act(async () => land({}));
    await flush();
    expect(toastMessages()).toEqual([]);
    root = createRoot(host);
  });
});

describe('deleting everything', () => {
  // A delete sweeps every store and can take a while: the reader may leave.
  it('is still said once the reader has left the card', async () => {
    let fail: (reason: unknown) => void = () => undefined;
    api.deleteBrain.mockReturnValueOnce(new Promise((_, reject) => (fail = reject)));
    await mount(<EchoDataCard />);
    await deleteEverything();
    act(() => root.unmount());
    await act(async () => fail(failures.noAnswer()));
    await flush();
    expect(toastMessages()).toEqual(['Delete failed. Nothing past the failing store was removed; try again.']);
    root = createRoot(host);
  });
});
