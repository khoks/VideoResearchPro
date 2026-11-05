/**
 * T-7.1.1.6 (D-112): what the channel page says about a low trust weight. The
 * re-rank takes the top passages by `distance / weight`, so a weight near 0
 * puts the channel last and, on a broad corpus, out of the answer. The slider's
 * text used to promise the opposite: "near 0 they appear only when little else
 * matches". The behaviour stays; the words now match it.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { idle } = vi.hoisted(() => ({ idle: () => ({ mutate: () => undefined, isPending: false, isError: false }) }));
vi.mock('../../hooks/useChannels', () => ({
  useChannel: () => ({
    data: {
      channel_id: 'c1',
      name: 'Tides',
      video_count: 3,
      subscribed: true,
      source_weight: 1,
      subscriber_count: null,
      last_synced_at: null,
    },
    isLoading: false,
    isError: false,
  }),
  useSetChannelWeight: idle,
  useSubscribeChannel: idle,
  useSyncChannel: idle,
  useUnsubscribeChannel: idle,
}));
vi.mock('../../hooks/useJobs', () => ({ useJob: () => ({ data: undefined }) }));
vi.mock('../../components/channel/ChannelTabs', () => ({ ChannelTabs: () => null }));

import { ChannelPage } from '../ChannelPage';

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('the trust weight text', () => {
  it('says a weight near 0 drops the channel out on a broad corpus', () => {
    const qc = new QueryClient();
    act(() =>
      root.render(
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/library/channels/c1']}>
            <Routes>
              <Route path="/library/channels/:channelId" element={<ChannelPage />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>,
      ),
    );
    const text = (host.querySelector('[data-slot="trust-weight"]')?.textContent ?? '').replace(/\s+/g, ' ');
    expect(text).toContain('near 0 the channel drops out of your answers on any topic your library covers broadly');
    expect(text).not.toContain('little else matches');
    // The rest of the promise stands.
    expect(text).toContain('never pulls in an off-topic passage');
    expect(text).toContain('only your answers change');
  });
});
