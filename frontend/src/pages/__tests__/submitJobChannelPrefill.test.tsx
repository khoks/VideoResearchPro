/**
 * T-8.10.1.7: the welcome wizard saves up to five channels and the first run
 * reads one. The submit page pre-fills its channel list with the ones no run
 * has named yet (`channels_not_yet_run` on `GET /auth/me/onboarding`) and
 * says where they came from. Never over a draft, a cloned run or a template,
 * and once per browser, so a list the reader cleared stays cleared.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let onboarding: { channels_not_yet_run?: string[] } | undefined;
vi.mock('../../hooks/useOnboarding', () => ({ useOnboarding: () => ({ data: onboarding }) }));
vi.mock('../../hooks/useJobs', () => ({ useCreateJob: () => ({ mutateAsync: vi.fn(), isPending: false }) }));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../hooks/useCapability', () => ({ useCapability: () => false }));
vi.mock('../../hooks/useTierCapabilities', () => ({ useTierCapabilities: () => ({ tier: 'free', numVideosCap: 100 }) }));
vi.mock('../../hooks/useJobTemplates', () => ({
  useJobTemplates: () => ({ data: [] }),
  useCreateTemplate: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useUpdateTemplate: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
}));

import { SubmitJobPage } from '../SubmitJobPage';

const NOTE = 'Filled in from the channels you chose when you started';

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(entry: string | { pathname: string; state: unknown } = '/jobs/new') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[entry]}>
          <SubmitJobPage />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

async function unmount() {
  act(() => root.unmount());
  root = createRoot(host);
}

const channelsTab = () =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Channels') as HTMLButtonElement;
const channelList = () => host.querySelector<HTMLTextAreaElement>('textarea[placeholder^="@3blue1brown"]');

async function openChannels() {
  act(() => channelsTab().click());
  await flush();
}

function type(el: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

beforeEach(() => {
  window.localStorage.clear();
  onboarding = { channels_not_yet_run: ['@second', 'https://youtube.com/@third'] };
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.localStorage.clear();
});

describe('submit page channel pre-fill', () => {
  it("fills an empty channel list with the wizard's channels no run has read, and says so", async () => {
    await mount();
    await openChannels();
    expect(channelList()!.value).toBe('@second\nhttps://youtube.com/@third');
    expect(host.textContent).toContain(NOTE);

    // Editing it makes it the reader's own list; the note goes.
    type(channelList()!, '@second');
    expect(host.textContent).not.toContain(NOTE);
  });

  it('a list the reader cleared is not filled in again on the next visit', async () => {
    await mount();
    await openChannels();
    type(channelList()!, '');
    await unmount();

    await mount();
    expect(channelList()!.value).toBe('');
    expect(host.textContent).not.toContain(NOTE);
  });

  it('a channel chosen later is offered even after an earlier pre-fill', async () => {
    await mount();
    await openChannels();
    type(channelList()!, '');
    await unmount();

    onboarding = { channels_not_yet_run: ['@second', 'https://youtube.com/@third', '@fourth'] };
    await mount();
    expect(channelList()!.value).toBe('@second\nhttps://youtube.com/@third\n@fourth');
  });

  it('never writes over a draft', async () => {
    window.localStorage.setItem('vrp:submit-form', JSON.stringify({ jobType: 'channel', channelList: '@my-draft' }));
    await mount();
    expect(channelList()!.value).toBe('@my-draft');
    expect(host.textContent).not.toContain(NOTE);
    await unmount();

    // Not offered then, so still offered once the draft is gone.
    window.localStorage.setItem('vrp:submit-form', JSON.stringify({ jobType: 'channel', channelList: '' }));
    await mount();
    expect(channelList()!.value).toBe('@second\nhttps://youtube.com/@third');
  });

  it('never over a cloned run or a template', async () => {
    const cloneFrom = {
      id: 'j1', job_type: 'channel', channel_list: ['@cloned'], status: 'completed', created_at: '2026-10-19T00:00:00',
    };
    await mount({ pathname: '/jobs/new', state: { cloneFrom } });
    expect(channelList()!.value).toBe('@cloned');
    await unmount();
    window.localStorage.clear();

    await mount({ pathname: '/jobs/new', state: { fromTemplateId: 'tpl-1' } });
    await openChannels();
    expect(channelList()!.value).toBe('');
  });

  it('does nothing when every chosen channel has been run, or the server is older', async () => {
    onboarding = { channels_not_yet_run: [] };
    await mount();
    await openChannels();
    expect(channelList()!.value).toBe('');
    await unmount();

    onboarding = {};
    await mount();
    expect(channelList()!.value).toBe('');
  });
});
