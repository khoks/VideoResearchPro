/**
 * T-3.4.1.22 on the two pages with Subscribe and Sync now, under the app's own
 * query client. A failed subscribe or sync was said in a line built from the
 * mutation's `isError` and again in the global toast, but for a full library and
 * a refused sync, which the toast already left to the page; the channel page's
 * trust weight did the same with a fixed sentence. Now the three hooks set
 * `meta`, each line gives the server's words through `inlineErrorMessage`, and a
 * 401 says nothing. A subscribe and a sync each keep a line, so one failure never
 * hides the other.
 *
 * On the library's channel list one line follows the last press of each button
 * across every row, so while one channel's subscribe or sync is in flight the
 * other rows' buttons wait: a second press would take the first one's line away
 * before it is written, and with it the only word of its failure.
 *
 * "A message" here is a toast or a line with `role="alert"`.
 *
 * Mutation checks, run on 2026-11-09: taking `meta` off `useSubscribeChannel` or
 * `useSetChannelWeight` fails that action's `words`, `noWords` and `noAnswer`
 * rows with the line and a toast, on both pages for subscribe; `apiErrorMessage`
 * back in place of `inlineErrorMessage` for the channel page's subscribe fails
 * its `sessionEnded` row with "Not authenticated"; the weight's old fixed
 * sentence fails its `words` and `sessionEnded` rows; the library's old
 * one-line `?:` fails its "keeps both lines"; and the rows' `subscribeHeld` or
 * `syncHeld` left out fails "waits for one channel's subscribe" or "sync".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Channel, SubscribeResponse } from '../../services/channelsApi';
import { createQueryClient } from '../../services/queryClient';
import {
  FAILURE_KINDS,
  SERVER_WORDS,
  clearToasts,
  expectedToasts,
  failures,
  flush,
  toastMessages,
} from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function channel(id: string, name: string): Channel {
  return {
    id,
    channel_id: id,
    name,
    url: null,
    subscribed: false,
    source_weight: 1,
    subscriber_count: 10,
    uploads_playlist_id: null,
    last_synced_at: null,
    created_at: null,
    video_count: 3,
  } as Channel;
}

const ONE = channel('UC1', 'First channel');
const TWO = channel('UC2', 'Second channel');
const STARTED: SubscribeResponse = { channel_id: 'UC1', job_id: null, sync_note: null };

const api = {
  subscribe: vi.fn<(id: string) => Promise<SubscribeResponse>>(),
  sync: vi.fn<(id: string) => Promise<SubscribeResponse>>(),
  setWeight: vi.fn<(id: string, weight: number) => Promise<Channel>>(),
};
vi.mock('../../services/channelsApi', () => ({
  channelsApi: {
    list: async () => [ONE, TWO],
    get: async (id: string) => (id === 'UC2' ? TWO : ONE),
    subscribe: (id: string) => api.subscribe(id),
    unsubscribe: async (id: string) => (id === 'UC2' ? TWO : ONE),
    sync: (id: string) => api.sync(id),
    setWeight: (id: string, weight: number) => api.setWeight(id, weight),
  },
}));
vi.mock('../../services/jobsApi', () => ({ jobsApi: { get: async () => ({ id: 'job-1', status: 'extracting' }) } }));
vi.mock('../../hooks/useLibrary', () => ({
  useLibraryVideos: () => ({ data: [], isLoading: false, isError: false, refetch: vi.fn() }),
  useLibraryVideoChannels: () => ({ data: [] }),
}));
vi.mock('../../components/channel/ChannelTabs', () => ({ ChannelTabs: () => null }));
vi.mock('../../components/library/PdfUploadZone', () => ({ PdfUploadZone: () => null }));
vi.mock('../../components/library/PasteUrlsForm', () => ({ PasteUrlsForm: () => null }));
vi.mock('../../components/tags', () => ({ TagFilterBar: () => null }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));

import { ChannelPage } from '../ChannelPage';
import { LibraryPage } from '../LibraryPage';

let host: HTMLDivElement;
let root: Root;

async function render(ui: React.ReactNode, path: string) {
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
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

const buttons = (label: string) =>
  Array.from(host.querySelectorAll('button')).filter((b) => b.textContent?.trim() === label) as HTMLButtonElement[];

async function press(b: HTMLButtonElement | undefined) {
  expect(b).toBeTruthy();
  await act(async () => b!.click());
  await flush();
}

/** Every message on screen: the toasts, then the text of each line with `role="alert"`. */
function messages(): string[] {
  const lines = Array.from(host.querySelectorAll('[role="alert"]')).flatMap((el) =>
    el.children.length > 0
      ? Array.from(el.children).map((child) => child.textContent?.trim() ?? '')
      : [el.textContent?.trim() ?? ''],
  );
  return [...toastMessages(), ...lines];
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
  api.subscribe.mockReset().mockResolvedValue(STARTED);
  api.sync.mockReset().mockResolvedValue(STARTED);
  api.setWeight.mockReset().mockResolvedValue(ONE);
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe.each([
  ['the channel page', channelPage],
  ['the library channel list', libraryChannels],
])('%s', (_name, open) => {
  it.each(FAILURE_KINDS)('says a failed subscribe (%s) once, where it was pressed', async (kind) => {
    api.subscribe.mockRejectedValueOnce(failures[kind]());
    await open();
    await press(buttons('Subscribe')[0]);
    expect(api.subscribe).toHaveBeenCalledWith('UC1');
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(expectedToasts(kind, 'Could not subscribe. Try again.'));
  });

  it.each(FAILURE_KINDS)('says a failed sync (%s) once, where it was pressed', async (kind) => {
    api.sync.mockRejectedValueOnce(failures[kind]());
    await open();
    await press(buttons('Sync now')[0]);
    expect(api.sync).toHaveBeenCalledWith('UC1');
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(expectedToasts(kind, 'Could not start a sync. Try again.'));
  });

  it('keeps both lines when a subscribe and a sync both fail', async () => {
    api.subscribe.mockRejectedValueOnce(failures.words());
    api.sync.mockRejectedValueOnce(failures.noAnswer());
    await open();
    await press(buttons('Subscribe')[0]);
    await press(buttons('Sync now')[0]);
    expect(messages()).toEqual([SERVER_WORDS, 'Could not start a sync. Try again.']);
  });

  it('says nothing when both go through', async () => {
    await open();
    await press(buttons('Subscribe')[0]);
    await press(buttons('Sync now')[0]);
    expect(messages()).toEqual([]);
  });
});

describe('the channel page’s trust weight', () => {
  it.each(FAILURE_KINDS)('says a failed save (%s) once, beside it', async (kind) => {
    api.setWeight.mockRejectedValueOnce(failures[kind]());
    await channelPage();
    const slider = host.querySelector('input[type="range"]') as HTMLInputElement;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(slider, '1.5');
      slider.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await press(buttons('Save')[0]);
    expect(api.setWeight).toHaveBeenCalledWith('UC1', 1.5);
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(expectedToasts(kind, 'Could not save the weight. Try again.'));
  });
});

describe('the library channel list, while one channel’s press is in flight', () => {
  it('waits for one channel’s subscribe before another’s goes', async () => {
    const request = held<SubscribeResponse>();
    api.subscribe.mockReturnValueOnce(request.promise);
    await libraryChannels();
    await press(buttons('Subscribe')[0]);
    expect(buttons('Subscribe').every((b) => b.disabled)).toBe(true);
    await press(buttons('Subscribe')[1]);
    expect(api.subscribe).toHaveBeenCalledTimes(1);
    await act(async () => request.fail(failures.words()));
    await flush();
    expect(messages()).toEqual([SERVER_WORDS]);
    expect(buttons('Subscribe').every((b) => !b.disabled)).toBe(true);
  });

  it('waits for one channel’s sync before another’s goes', async () => {
    const request = held<SubscribeResponse>();
    api.sync.mockReturnValueOnce(request.promise);
    await libraryChannels();
    await press(buttons('Sync now')[0]);
    expect(buttons('Sync now')).toHaveLength(2);
    expect(buttons('Sync now').every((b) => b.disabled)).toBe(true);
    await press(buttons('Sync now')[1]);
    expect(api.sync).toHaveBeenCalledTimes(1);
    await act(async () => request.fail(failures.noWords()));
    await flush();
    expect(messages()).toEqual(['Could not start a sync. Try again.']);
    expect(buttons('Sync now').every((b) => !b.disabled)).toBe(true);
  });
});
