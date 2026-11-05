/**
 * T-5.2.15 on the two pages with a Subscribe and a Sync now button. Subscribing
 * always succeeds, so a first sync that could not start comes back as a 200
 * with no job and a `sync_note`, and the page has to say so: the button flips
 * to "Subscribed" and nothing else would tell the reader no sync ran. A
 * refused Sync now is a 429 like any other job's, said where it was pressed.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AxiosError, AxiosHeaders } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { globalErrorToastMessage } from '../../utils/apiError';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const NOTE =
  'You are subscribed to A channel, but the first sync has not started. You have 5 active jobs, and your ' +
  "limit is 5 at once. Other people's jobs do not count toward it. Wait for one to finish, or cancel one. " +
  'Then use Sync now to start it.';
const LIMIT =
  "You have 5 active jobs, and your limit is 5 at once. Other people's jobs do not count toward it. " +
  'Wait for one to finish, or cancel one.';

function refusal(url: string): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError(
    'Request failed with status code 429',
    'ERR_BAD_REQUEST',
    { url, headers },
    undefined,
    { status: 429, statusText: 'Too Many Requests', headers, config: { url, headers }, data: { detail: LIMIT } },
  );
}

const CHANNEL = {
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
};

// What each hook's `mutate` answers, and the pending/error state it reports.
const answers = {
  subscribe: { channel_id: 'UC1', job_id: null as string | null, sync_note: NOTE as string | null },
  sync: { channel_id: 'UC1', job_id: 'job-1' as string | null, sync_note: null as string | null },
};
const syncState = { isError: false, error: null as unknown };

vi.mock('../../hooks/useChannels', () => ({
  useChannels: () => ({ data: [CHANNEL], isLoading: false, isError: false }),
  useChannel: () => ({ data: CHANNEL, isLoading: false, isError: false }),
  useSubscribeChannel: () => ({
    mutate: (_id: string, options?: { onSuccess?: (r: typeof answers.subscribe) => void }) =>
      options?.onSuccess?.(answers.subscribe),
    isPending: false,
    isError: false,
    error: null,
  }),
  useUnsubscribeChannel: () => ({ mutate: vi.fn(), isPending: false, isError: false, error: null }),
  useSyncChannel: () => ({
    mutate: (_id: string, options?: { onSuccess?: (r: typeof answers.sync) => void }) =>
      options?.onSuccess?.(answers.sync),
    isPending: false,
    ...syncState,
  }),
  useSetChannelWeight: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}));
vi.mock('../../hooks/useJobs', () => ({ useJob: () => ({ data: undefined }) }));
vi.mock('../../hooks/useLibrary', () => ({
  useLibraryVideos: () => ({ data: [], isLoading: false, isError: false, refetch: vi.fn() }),
  useLibraryVideoChannels: () => ({ data: [] }),
}));
vi.mock('../../components/channel/ChannelTabs', () => ({ ChannelTabs: () => null }));
vi.mock('../../components/library/PdfUploadZone', () => ({ PdfUploadZone: () => null }));
vi.mock('../../components/library/PasteUrlsForm', () => ({ PasteUrlsForm: () => null }));
vi.mock('../../components/tags', () => ({ TagFilterBar: () => null }));

import { ChannelPage } from '../ChannelPage';
import { LibraryPage } from '../LibraryPage';

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function render(ui: React.ReactNode, path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const channelPage = () =>
  render(
    <Routes>
      <Route path="/library/channels/:channelId" element={<ChannelPage />} />
    </Routes>,
    '/library/channels/UC1',
  );
const libraryChannels = () => render(<LibraryPage />, '/library?tab=channels');

const button = (label: string) =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as HTMLButtonElement;
const note = () => host.querySelector('[data-testid="channel-sync-note"]');

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  answers.subscribe = { channel_id: 'UC1', job_id: null, sync_note: NOTE };
  answers.sync = { channel_id: 'UC1', job_id: 'job-1', sync_note: null };
  syncState.isError = false;
  syncState.error = null;
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe.each([
  ['the channel page', channelPage],
  ['the library channel list', libraryChannels],
])('%s', (_name, open) => {
  it('says plainly when subscribing started no sync', async () => {
    await open();
    expect(note()).toBeNull();

    await act(async () => button('Subscribe').click());
    await flush();

    expect(note()?.textContent).toBe(NOTE);
    expect(note()?.getAttribute('role')).toBe('status');
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });

  it('says nothing when the first sync started', async () => {
    answers.subscribe = { channel_id: 'UC1', job_id: 'job-1', sync_note: null };
    await open();

    await act(async () => button('Subscribe').click());
    await flush();

    expect(note()).toBeNull();
  });

  it('says a sync that could not be queued, and the next try clears it', async () => {
    answers.sync = {
      channel_id: 'UC1',
      job_id: null,
      sync_note: 'The sync could not be queued. Try Sync now again in a moment.',
    };
    await open();

    await act(async () => button('Sync now').click());
    await flush();
    expect(note()?.textContent).toContain('could not be queued');

    answers.sync = { channel_id: 'UC1', job_id: 'job-1', sync_note: null };
    await act(async () => button('Sync now').click());
    await flush();
    expect(note()).toBeNull();
  });

  it('shows a refused Sync now in the server\'s words, where it was pressed', async () => {
    syncState.isError = true;
    syncState.error = refusal('/channels/UC1/sync');
    await open();

    expect(host.querySelector('[role="alert"]')?.textContent).toBe(LIMIT);
  });
});

describe('the global error toast', () => {
  it('stays out of the way of a refused sync, which its page shows', () => {
    expect(globalErrorToastMessage(refusal('/channels/UC1/sync'))).toBeNull();
  });

  it('still says a refused job, which has no such place', () => {
    expect(globalErrorToastMessage(refusal('/jobs'))).toBe(LIMIT);
  });
});
