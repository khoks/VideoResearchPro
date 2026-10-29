/**
 * T-5.2.10: a document-cap refusal (429, `detail.resource === 'documents'`,
 * `detail.message`) is shown where the action started — the approval
 * section of a run and the channel page's subscribe / sync buttons — and the
 * Subscription page's usage line reads the same count. These fail if the
 * refusal is swallowed (the approval button used to fire and forget) or if
 * the object-shaped detail is not read.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AxiosError, AxiosHeaders } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Video } from '../../types/video';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const CAP_MESSAGE =
  'Your library holds 498 of the 500 documents the Free plan allows, so there is room for 2 more. ' +
  'This approval would add 3 documents you do not have yet. Deselect at least 1, or move to a plan with a higher cap.';

function capRefusal(message = CAP_MESSAGE): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError('Request failed with status code 429', 'ERR_BAD_REQUEST', undefined, undefined, {
    status: 429,
    statusText: 'Too Many Requests',
    headers,
    config: { headers },
    data: {
      detail: {
        error: 'quota_exceeded',
        resource: 'documents',
        consumed: 498,
        limit: 500,
        requested: 3,
        available: 2,
        retry_at: null,
        retry_after_sec: null,
        message,
      },
    },
  });
}

// ChannelPage's hooks, steered per test.
const channelState = {
  subscribe: { isError: false, error: null as unknown },
  sync: { isError: false, error: null as unknown },
};
vi.mock('../../hooks/useChannels', () => ({
  useChannel: () => ({
    data: {
      id: 'UC1',
      channel_id: 'UC1',
      name: 'A channel',
      url: null,
      subscribed: false,
      source_weight: 1,
      subscriber_count: 10,
      uploads_playlist_id: null,
      last_synced_at: null,
      created_at: null,
      video_count: 3,
    },
    isLoading: false,
    isError: false,
  }),
  useSubscribeChannel: () => ({ mutate: vi.fn(), isPending: false, ...channelState.subscribe }),
  useUnsubscribeChannel: () => ({ mutate: vi.fn(), isPending: false, isError: false, error: null }),
  useSyncChannel: () => ({ mutate: vi.fn(), isPending: false, ...channelState.sync }),
  useSetChannelWeight: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}));
vi.mock('../../hooks/useJobs', () => ({ useJob: () => ({ data: undefined }) }));
vi.mock('../../components/channel/ChannelTabs', () => ({ ChannelTabs: () => null }));

import { VideoApprovalSection } from '../JobDetailPage';
import { ChannelPage } from '../ChannelPage';

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

function render(ui: React.ReactNode, path = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
      </QueryClientProvider>,
    ),
  );
}

function video(n: number): Video {
  return {
    id: `d${n}`,
    video_id: `v${n}`,
    document_id: `d${n}`,
    // An unregistered type renders the compact fallback row: no card config needed.
    source_type: 'fixture' as Video['source_type'],
    source_id: `v${n}`,
    source_url: null,
    source_metadata: {},
    classification: null,
    title: `Candidate ${n}`,
    channel_name: 'C',
    channel_id: null,
    url: `https://example.com/${n}`,
    duration_seconds: 60,
    published_at: null,
    thumbnail_url: null,
    approved: true,
    transcript_status: 'pending',
    transcript_word_count: null,
    transcript_language: null,
  };
}

const approveButton = () =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.includes('Approve')) as HTMLButtonElement;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  channelState.subscribe = { isError: false, error: null };
  channelState.sync = { isError: false, error: null };
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('approval refused by the document cap', () => {
  it('shows the server message and keeps the selection', async () => {
    const onApprove = vi.fn(async () => {
      throw capRefusal();
    });
    render(<VideoApprovalSection videos={[video(1), video(2), video(3)]} jobId="j1" onApprove={onApprove} />);
    await flush();
    expect(host.querySelector('[role="alert"]')).toBeNull();

    await act(async () => {
      approveButton().click();
    });
    await flush();

    expect(onApprove).toHaveBeenCalledWith({ id: 'j1', data: { approved_video_ids: ['v1', 'v2', 'v3'] } });
    expect(host.querySelector('[role="alert"]')?.textContent).toBe(CAP_MESSAGE);
    expect(host.textContent).toContain('3/3 selected');
  });

  it('clears the message once an approval goes through', async () => {
    let refuse = true;
    const onApprove = vi.fn(async () => {
      if (refuse) throw capRefusal();
      return {};
    });
    render(<VideoApprovalSection videos={[video(1)]} jobId="j2" onApprove={onApprove} />);
    await flush();
    await act(async () => approveButton().click());
    await flush();
    expect(host.querySelector('[role="alert"]')).not.toBeNull();

    refuse = false;
    await act(async () => approveButton().click());
    await flush();
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });
});

describe('channel page subscribe / sync refused by the document cap', () => {
  const SYNC_MESSAGE =
    "Your library is at the Free plan's cap of 500 documents. A sync cannot add anything new until you move to a plan with a higher cap. Documents already in your library stay.";

  it.each([
    ['subscribe', () => (channelState.subscribe = { isError: true, error: capRefusal(SYNC_MESSAGE) })],
    ['sync', () => (channelState.sync = { isError: true, error: capRefusal(SYNC_MESSAGE) })],
  ])('shows the refusal for %s under the buttons', async (_label, refuse) => {
    refuse();
    render(
      <Routes>
        <Route path="/library/channels/:channelId" element={<ChannelPage />} />
      </Routes>,
      '/library/channels/UC1',
    );
    await flush();
    expect(host.querySelector('header [role="alert"]')?.textContent).toBe(SYNC_MESSAGE);
  });

  it('shows nothing when neither action failed', async () => {
    render(
      <Routes>
        <Route path="/library/channels/:channelId" element={<ChannelPage />} />
      </Routes>,
      '/library/channels/UC1',
    );
    await flush();
    expect(host.querySelector('header [role="alert"]')).toBeNull();
  });
});
