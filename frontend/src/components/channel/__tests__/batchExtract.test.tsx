/**
 * T-1.15.3.7: "Extract knowledge for all" takes one depth for the batch. The
 * real component and the real `knowledgeApi` run here, with only the HTTP layer
 * replaced, so the assertion is the POST each document gets. Auto must be the
 * request the page sent before the select existed.
 *
 * Mutation check, run by hand on 2026-11-04: `runBatch` calling
 * `knowledgeApi.extract(id)` again fails the depth test.
 *
 * T-1.15.3.10: the select starts from the account's default depth, under D-145's
 * rule: it stands in where the control is on screen, a choice on the page wins, and
 * the server is never asked to apply it. The real `usePreferredDepth` reads the
 * query `AppLayout` keeps alive. Mutation checks, run by hand on 2026-11-05: a
 * start of null in place of `usePreferredDepth()` fails "starts from" and "arrives
 * after"; `useDepthChoice` reading a pick of Auto as no pick fails "Auto picked".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const postMock = vi.fn();
vi.mock('../../../services/api', () => ({
  default: { post: (...args: unknown[]) => postMock(...args) },
}));
vi.mock('../../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../../hooks/useChannelIntelligence', () => ({
  useQuota: () => ({ data: undefined, isLoading: false }),
  intelligenceKey: (id: string) => ['channelIntelligence', id],
}));

import { BatchExtract } from '../BatchExtract';
import { ME_QUERY_KEY } from '../../../hooks/useMe';

const DOCS = [
  { id: 'd1', title: 'First', url: '' },
  { id: 'd2', title: 'Second', url: '' },
];

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

let client: QueryClient;

function mount(preferred?: string | null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client = qc;
  if (preferred !== undefined) qc.setQueryData(ME_QUERY_KEY, { id: 'u1', email: 'a@x', tier: 'pro', preferred_output_length: preferred });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <BatchExtract channelId="c1" extractable={DOCS} />
      </QueryClientProvider>,
    ),
  );
}

const button = (label: string) =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as HTMLButtonElement;

const depthSelect = () => host.querySelector<HTMLSelectElement>('select[aria-label="Report depth"]');

function pick(depth: string) {
  const select = depthSelect()!;
  act(() => {
    select.value = depth;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

function openConfirm() {
  act(() => button('Extract knowledge for 2 documents').click());
}

async function start() {
  await act(async () => button('Start').click());
  await flush();
}

beforeEach(() => {
  postMock.mockReset();
  postMock.mockResolvedValue({ data: {} });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("BatchExtract: the account's default depth (T-1.15.3.10)", () => {
  it('starts from it, shown where the batch is confirmed, and sends it', async () => {
    mount('brief');
    openConfirm();
    expect(depthSelect()!.value).toBe('brief');
    await start();
    expect(postMock.mock.calls).toEqual([
      ['/videos/d1/extract-knowledge', null, { params: { output_length: 'brief' } }],
      ['/videos/d2/extract-knowledge', null, { params: { output_length: 'brief' } }],
    ]);
  });

  it('takes a preference that arrives after the first render', async () => {
    mount();
    openConfirm();
    expect(depthSelect()!.value).toBe('');
    await act(async () => client.setQueryData(ME_QUERY_KEY, { id: 'u1', email: 'a@x', tier: 'pro', preferred_output_length: 'deep' }));
    await flush();
    expect(depthSelect()!.value).toBe('deep');
  });

  it('lets a depth picked on the page win', async () => {
    mount('brief');
    openConfirm();
    pick('deep');
    await start();
    expect(postMock.mock.calls[0]).toEqual(['/videos/d1/extract-knowledge', null, { params: { output_length: 'deep' } }]);
  });

  it('Auto picked on the page wins too, and sends none', async () => {
    mount('brief');
    openConfirm();
    pick('');
    await start();
    expect(postMock.mock.calls[0]).toEqual(['/videos/d1/extract-knowledge', null, { params: undefined }]);
  });

  it('a preference of Auto is the same request as no preference', async () => {
    mount('auto');
    openConfirm();
    expect(depthSelect()!.value).toBe('');
    await start();
    expect(postMock.mock.calls[0]).toEqual(['/videos/d1/extract-knowledge', null, { params: undefined }]);
  });

  it('spends nothing until Start', () => {
    mount('deep');
    openConfirm();
    expect(postMock).not.toHaveBeenCalled();
  });
});

describe('BatchExtract: one depth for the batch', () => {
  it('offers the depth where the batch is confirmed, on Auto', () => {
    mount();
    expect(depthSelect()).toBeNull();
    openConfirm();
    expect(depthSelect()!.value).toBe('');
    expect(depthSelect()!.options[0].textContent).toBe('Auto');
  });

  it("Auto sends no preference: today's request for every document", async () => {
    mount();
    openConfirm();
    await start();
    expect(postMock.mock.calls).toEqual([
      ['/videos/d1/extract-knowledge', null, { params: undefined }],
      ['/videos/d2/extract-knowledge', null, { params: undefined }],
    ]);
  });

  it('sends the chosen depth for every document, and never force', async () => {
    mount();
    openConfirm();
    pick('deep');
    await start();
    expect(postMock.mock.calls).toEqual([
      ['/videos/d1/extract-knowledge', null, { params: { output_length: 'deep' } }],
      ['/videos/d2/extract-knowledge', null, { params: { output_length: 'deep' } }],
    ]);
  });
});
