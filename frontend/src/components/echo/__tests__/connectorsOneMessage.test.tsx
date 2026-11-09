/**
 * One message per failure for Echo's connectors, under the app's own query
 * client.
 *
 * T-3.4.1.18: the callback page says a failed connection as the page itself, and
 * the global toast said it again. Now `useCompleteConnector` sets
 * `meta: ERRORS_SHOWN_HERE`, and a 401 says nothing.
 *
 * T-3.4.1.20: Disconnect awaited `mutateAsync` with nothing to catch it, so a
 * failure rejected unhandled; the global toast already said it. Now it calls
 * `mutate`, the toast stays the one message, the dialog stays open to try again,
 * and nothing rejects unhandled. Vitest fails a run on an unhandled rejection,
 * and the test also listens for one itself, so the failure is pinned to the test
 * that caused it.
 *
 * Mutation checks, run on 2026-11-09: taking `meta` off `useCompleteConnector`
 * fails the callback page's rows but `sessionEnded` with the page's line and a
 * toast; `apiErrorMessage` back for `inlineErrorMessage` there fails
 * `sessionEnded`; putting back `await revoke.mutateAsync(...)` fails every
 * failed-disconnect row on "nothing rejects unhandled".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConnectorItem } from '../../../services/echoApi';
import { createQueryClient } from '../../../services/queryClient';
import {
  FAILURE_KINDS,
  SERVER_WORDS,
  clearToasts,
  expectedToasts,
  failures,
  flush,
  press,
  toastMessages,
  type FailureKind,
} from '../../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const complete = vi.fn<(name: string, body: { code: string; state: string }) => Promise<unknown>>();
const revoke = vi.fn<(name: string) => Promise<void>>();

vi.mock('../../../services/echoApi', async (orig) => ({
  ...(await orig<typeof import('../../../services/echoApi')>()),
  echoApi: {
    completeConnector: (name: string, body: { code: string; state: string }) => complete(name, body),
    revokeConnector: (name: string) => revoke(name),
    syncConnector: vi.fn(),
    authorizeConnector: vi.fn(),
  },
}));

import { ConnectorsPanel } from '../ConnectorsPanel';
import { EchoConnectorCallbackPage } from '../../../pages/EchoConnectorCallbackPage';

const GITHUB: ConnectorItem = {
  name: 'github',
  display_name: 'GitHub',
  privacy_weight: 'low',
  consent_disclosure: 'Echo reads your public GitHub activity.',
  consent_version: '2026-10-19',
  event_types: ['pushed_commit'],
  configured: true,
  connected: true,
  grant: {
    account_label: 'octocat',
    granted_at: '2026-10-20T09:00:00Z',
    consent_version: '2026-10-19',
    consent_outdated: false,
    status: 'idle',
    last_sync_at: '2026-11-01T09:00:00Z',
    backfilled_at: '2026-10-20T09:05:00Z',
    last_error: null,
    last_counts: null,
    events: 12,
  },
};

let host: HTMLDivElement;
let root: Root;
let rejections: unknown[];
const onRejection = (reason: unknown) => rejections.push(reason);

async function mount(node: React.ReactNode, path = '/echo') {
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/echo/connectors/:name/callback" element={<EchoConnectorCallbackPage />} />
            <Route path="/echo" element={node} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

/** Every message on screen: the toasts, then each line with `role="alert"`. */
function messages(): string[] {
  const lines = Array.from(document.querySelectorAll('[role="alert"]')).map(
    (el) => el.querySelector('p')?.textContent?.trim() ?? el.textContent?.trim() ?? '',
  );
  return [...toastMessages(), ...lines];
}

const dialogOpen = () => !!document.querySelector('[role="dialog"]');

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  complete.mockReset().mockResolvedValue({});
  revoke.mockReset().mockResolvedValue(undefined);
  clearToasts();
  rejections = [];
  process.on('unhandledRejection', onRejection);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  process.off('unhandledRejection', onRejection);
});

describe('the callback page', () => {
  const CALLBACK = '/echo/connectors/github/callback?code=c0de&state=st4te';
  const FALLBACK = 'Connecting failed. Start again from the Echo page.';

  it.each(FAILURE_KINDS)('says a failed connection (%s) once, as the page', async (kind) => {
    complete.mockRejectedValueOnce(failures[kind]());
    await mount(null, CALLBACK);
    expect(complete).toHaveBeenCalledWith('github', { code: 'c0de', state: 'st4te' });
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(expectedToasts(kind, FALLBACK));
    expect(rejections).toEqual([]);
  });
});

describe('disconnecting', () => {
  /** What the global toast says for each failure: the server's words, else axios's. */
  const TOAST_SAYS: Record<FailureKind, string[]> = {
    words: [SERVER_WORDS],
    noWords: ['Request failed with status code 500'],
    noAnswer: ['Network Error'],
    sessionEnded: [],
  };

  async function disconnect() {
    await mount(<ConnectorsPanel connectors={[GITHUB]} />);
    await press('Disconnect');
    expect(dialogOpen()).toBe(true);
    await press('Disconnect and delete');
  }

  it.each(FAILURE_KINDS)('says a failure (%s) once, keeps the dialog, and nothing rejects unhandled', async (kind) => {
    revoke.mockRejectedValueOnce(failures[kind]());
    await disconnect();
    await flush();
    expect(revoke).toHaveBeenCalledWith('github');
    expect(messages()).toEqual(TOAST_SAYS[kind]);
    expect(dialogOpen()).toBe(true);
    expect(rejections).toEqual([]);
  });

  it('closes the dialog once it goes through', async () => {
    await disconnect();
    expect(revoke).toHaveBeenCalledTimes(1);
    expect(dialogOpen()).toBe(false);
    expect(messages()).toEqual([]);
  });
});
