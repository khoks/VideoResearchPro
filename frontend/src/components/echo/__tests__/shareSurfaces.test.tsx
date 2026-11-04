/**
 * What the share surfaces show (T-3.7.6.1, T-3.7.4.1): the iPhone steps where
 * tokens are managed, and a mail in the inbox with its sender and no way to
 * mark it as the user's own words.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Share } from '../../../services/echoApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { state, mutation } = vi.hoisted(() => ({
  state: { shares: [] as unknown[] },
  mutation: () => ({ mutate: () => undefined, isPending: false }),
}));

vi.mock('../../../hooks/useEcho', () => ({
  useShares: () => ({ data: { items: state.shares, total: state.shares.length }, isLoading: false, isError: false }),
  useImports: () => ({ data: { items: [] } }),
  useUpdateShare: mutation,
  useDeleteShare: mutation,
  useReprocessShare: mutation,
  useAddShareToLibrary: mutation,
  useShareTokens: () => ({ data: { items: [], max: 10 }, isLoading: false }),
  useCreateShareToken: mutation,
  useRevokeShareToken: mutation,
}));
vi.mock('../../../hooks/useTierCapabilities', () => ({
  useTierCapabilities: () => ({ has: () => true, tier: 'studio', isLoading: false }),
}));
vi.mock('../../../services/echoApi', () => ({ echoApi: { sharesSeen: async () => undefined } }));
vi.mock('../../../services/api', () => ({ default: { defaults: { baseURL: 'https://app.example/api/v1' } } }));
vi.mock('../QuickShare', () => ({ QuickShare: () => null }));

import { EchoInboxPage } from '../../../pages/EchoInboxPage';
import { ShareTokensCard } from '../ShareTokensCard';

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

let host: HTMLDivElement;
let root: Root;

async function show(node: React.ReactNode) {
  await act(async () => root.render(<MemoryRouter>{node}</MemoryRouter>));
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const hasButton = (name: string) => [...host.querySelectorAll('button')].some((b) => b.textContent === name);

describe('the inbox', () => {
  it('shows who a mail claims to be from and what it held, and offers no own-words button', async () => {
    state.shares = [
      share({
        surface: 'email_in',
        content_type: 'email',
        source: { from: 'me@example.com', title: 'Tariffs', attachments: [{ name: 'scan.png', type: 'image/png' }] },
      }),
    ];
    await show(<EchoInboxPage />);
    expect(host.textContent).toContain('By email from me@example.com');
    expect(host.textContent).toContain('1 attachment not read: scan.png');
    expect(hasButton('These are my words')).toBe(false);
    expect(hasButton('Add why')).toBe(true);
  });

  it('keeps the button for every other surface', async () => {
    state.shares = [share({ surface: 'os_share', source: { title: 'the share sheet' } })];
    await show(<EchoInboxPage />);
    expect(hasButton('These are my words')).toBe(true);
    expect(host.textContent).toContain('From the share sheet');
  });
});

describe('where tokens are managed', () => {
  it('shows the iPhone steps with this server’s address, and says they are untried', async () => {
    await show(<ShareTokensCard />);
    expect(host.querySelector('details ol')?.children).toHaveLength(6);
    expect(host.textContent).toContain('https://app.example/api/v1/echo/shares');
    expect(host.textContent).toContain('not been run on a real iPhone');
  });
});
