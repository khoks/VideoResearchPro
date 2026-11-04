/**
 * T-1.15.3.7: "Extract knowledge for all" takes one depth for the batch. The
 * real component and the real `knowledgeApi` run here, with only the HTTP layer
 * replaced, so the assertion is the POST each document gets. Auto must be the
 * request the page sent before the select existed.
 *
 * Mutation check, run by hand on 2026-11-04: `runBatch` calling
 * `knowledgeApi.extract(id)` again fails the depth test.
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

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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
