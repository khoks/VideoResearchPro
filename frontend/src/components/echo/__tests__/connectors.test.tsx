/**
 * S-3.2.1: the consent screen shows the disclosure and what is recorded
 * before any redirect, and sends the version it showed; the callback page
 * hands the provider's code back and returns to Echo; a denial says so.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConnectorsPanel, humanize } from '../ConnectorsPanel';
import { summarize } from '../ActivityTimeline';
import { EchoConnectorCallbackPage } from '../../../pages/EchoConnectorCallbackPage';
import type { ConnectorItem } from '../../../services/echoApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const authorizeMock = vi.fn(async (_name: string, _v: string) => ({ authorize_url: 'https://github.com/login/oauth/authorize?x=1' }));
const completeMock = vi.fn(async (_name: string, _b: { code: string; state: string }) => ({}));
vi.mock('../../../services/echoApi', async (orig) => ({
  ...(await orig<typeof import('../../../services/echoApi')>()),
  echoApi: {
    authorizeConnector: (n: string, v: string) => authorizeMock(n, v),
    completeConnector: (n: string, b: { code: string; state: string }) => completeMock(n, b),
    syncConnector: vi.fn(),
    revokeConnector: vi.fn(),
  },
}));

const GITHUB: ConnectorItem = {
  name: 'github',
  display_name: 'GitHub',
  privacy_weight: 'low',
  consent_disclosure: 'Echo reads your public GitHub activity: commits you push and their messages.',
  consent_version: '2026-10-19',
  event_types: ['pushed_commit', 'opened_pull_request'],
  configured: true,
  connected: false,
  grant: null,
};

let host: HTMLDivElement;
let root: Root;
let assign: ReturnType<typeof vi.fn>;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

function render(node: React.ReactNode, path = '/echo') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
      </QueryClientProvider>,
    ),
  );
}

const button = (text: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === text) as HTMLButtonElement | undefined;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  authorizeMock.mockClear();
  completeMock.mockClear();
  assign = vi.fn();
  Object.defineProperty(window, 'location', { value: { ...window.location, assign }, writable: true });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.innerHTML = '';
});

describe('consent before connecting', () => {
  it('shows the disclosure and what is recorded, then redirects with the version it showed', async () => {
    render(<ConnectorsPanel connectors={[GITHUB]} />);
    expect(authorizeMock).not.toHaveBeenCalled();
    act(() => button('Connect')!.click());
    const dialog = document.querySelector('[data-consent-dialog]')!;
    expect(dialog.textContent).toContain('commits you push and their messages');
    expect(dialog.textContent).toContain('Pushed commit');
    expect(dialog.textContent).toContain('Opened pull request');
    expect(dialog.textContent).toContain('Low privacy weight');
    expect(authorizeMock).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();

    await act(async () => button('Continue to GitHub')!.click());
    await flush();
    expect(authorizeMock).toHaveBeenCalledWith('github', '2026-10-19');
    expect(assign).toHaveBeenCalledWith('https://github.com/login/oauth/authorize?x=1');
  });

  it('cannot connect what the install has not set up', () => {
    render(<ConnectorsPanel connectors={[{ ...GITHUB, configured: false }]} />);
    expect(button('Connect')!.disabled).toBe(true);
    expect(host.textContent).toContain('Not set up on this install.');
  });

  it('shows a connected grant and asks to reconnect after an auth failure', () => {
    render(
      <ConnectorsPanel
        connectors={[
          {
            ...GITHUB,
            connected: true,
            grant: {
              account_label: 'octocat', granted_at: null, consent_version: '2026-10-19', consent_outdated: false,
              status: 'error', last_sync_at: null, backfilled_at: null,
              last_error: 'Reconnect to sync: GitHub refused the token.', last_counts: null, events: 12,
            },
          },
        ]}
      />,
    );
    expect(host.textContent).toContain('Connected as octocat · 12 events');
    expect(host.textContent).toContain('Reconnect to sync');
    expect(button('Reconnect')).toBeDefined();
    expect(button('Disconnect')).toBeDefined();
  });
});

function Where() {
  const loc = useLocation();
  return <p data-where="">{loc.pathname + loc.search}</p>;
}

describe('the callback page', () => {
  it('hands the code and state back, then returns to Echo', async () => {
    render(
      <Routes>
        <Route path="/echo/connectors/:name/callback" element={<EchoConnectorCallbackPage />} />
        <Route path="/echo" element={<Where />} />
      </Routes>,
      '/echo/connectors/github/callback?code=abc&state=xyz',
    );
    await flush();
    expect(completeMock).toHaveBeenCalledWith('github', { code: 'abc', state: 'xyz' });
    expect(host.querySelector('[data-where]')!.textContent).toBe('/echo?connected=github');
  });

  it('says so when the user declined at the provider, and posts nothing', async () => {
    render(
      <Routes>
        <Route path="/echo/connectors/:name/callback" element={<EchoConnectorCallbackPage />} />
      </Routes>,
      '/echo/connectors/github/callback?error=access_denied&state=xyz',
    );
    await flush();
    expect(completeMock).not.toHaveBeenCalled();
    expect(host.textContent).toContain('You declined on the provider');
  });
});

describe('timeline text', () => {
  it('names events and summarises them from what they carry', () => {
    expect(humanize('pushed_commit')).toBe('Pushed commit');
    const base = { id: '1', connector: 'github', event_type: 'pushed_commit', occurred_at: '', linked_document_id: null };
    expect(summarize({ ...base, payload: { repo: 'me/parser' }, text_content: 'Fix the tokenizer\n\nlong body' })).toBe(
      'Fix the tokenizer in me/parser',
    );
    expect(summarize({ ...base, payload: { title: 'An article' }, text_content: null })).toBe('An article');
    expect(summarize({ ...base, payload: {}, text_content: null })).toBe('');
  });
});
