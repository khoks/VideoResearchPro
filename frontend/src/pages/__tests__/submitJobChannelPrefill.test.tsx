/**
 * T-8.10.1.7: the welcome wizard saves up to five channels and the first run
 * reads one. The submit page pre-fills its channel list with the ones no run
 * has named yet (`channels_not_yet_run` on `GET /auth/me/onboarding`) and
 * says where they came from. Never over a draft, a cloned run or a template,
 * and once per browser, so a list the reader cleared stays cleared. The offer
 * is made, and spent, only when the Channels form is on screen: on the default
 * Topic tab nobody would see it.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let onboarding: { channels_not_yet_run?: string[] } | undefined;
vi.mock('../../hooks/useOnboarding', () => ({ useOnboarding: () => ({ data: onboarding }) }));
const mutateAsync = vi.fn();
vi.mock('../../hooks/useJobs', () => ({ useCreateJob: () => ({ mutateAsync, isPending: false }) }));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../hooks/useCapability', () => ({ useCapability: () => false }));
vi.mock('../../hooks/useTierCapabilities', () => ({ useTierCapabilities: () => ({ tier: 'free', numVideosCap: 100 }) }));
let templates: unknown[] = [];
vi.mock('../../hooks/useJobTemplates', () => ({
  useJobTemplates: () => ({ data: templates }),
  useCreateTemplate: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useUpdateTemplate: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
}));

import { SubmitJobPage } from '../SubmitJobPage';

const NOTE = 'Filled in from the channels you chose when you started';
const FORM_KEY = 'vrp:submit-form';
const OFFERED_KEY = 'vrp:submit-prefilled-channels';
const FILLED = '@second\nhttps://youtube.com/@third';

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
const topicTab = () =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Topic') as HTMLButtonElement;
const channelList = () => host.querySelector<HTMLTextAreaElement>('textarea[placeholder^="@3blue1brown"]');
const topicInput = () => host.querySelector<HTMLInputElement>('input[placeholder^="e.g. Quantum"]');
const savedForm = () => JSON.parse(window.localStorage.getItem(FORM_KEY) ?? '{}') as { channelList?: string };

async function openChannels() {
  act(() => channelsTab().click());
  await flush();
}

function type(el: HTMLTextAreaElement | HTMLInputElement, value: string) {
  const proto = el instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

beforeEach(() => {
  window.localStorage.clear();
  mutateAsync.mockReset();
  mutateAsync.mockResolvedValue({ id: 'j1' });
  templates = [];
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

  it('spends nothing on a reader who never opens Channels', async () => {
    await mount();
    expect(topicInput()).not.toBeNull();
    expect(window.localStorage.getItem(OFFERED_KEY)).toBeNull();
    expect(savedForm().channelList).toBe('');

    // A topic run: submitting removes the draft, and the channels with it.
    type(topicInput()!, 'Interest rates');
    await act(async () => (host.querySelector('button[type="submit"]') as HTMLButtonElement).click());
    await flush();
    expect(mutateAsync).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem(FORM_KEY)).toBeNull();
    await unmount();

    await mount();
    await openChannels();
    expect(channelList()!.value).toBe(FILLED);
    expect(host.textContent).toContain(NOTE);
  });

  it('Reset on the Topic tab spends nothing either', async () => {
    await mount();
    const reset = Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Reset form')!;
    act(() => reset.click());
    await flush();
    await openChannels();
    expect(channelList()!.value).toBe(FILLED);
  });

  it('fills the list when Channels is opened, and only once in a visit', async () => {
    await mount();
    await openChannels();
    expect(channelList()!.value).toBe(FILLED);
    type(channelList()!, '');

    act(() => topicTab().click());
    await flush();
    await openChannels();
    expect(channelList()!.value).toBe('');
    expect(host.textContent).not.toContain(NOTE);
  });

  it('a saved topic draft is a draft: nothing is written into it and the offer waits', async () => {
    window.localStorage.setItem(FORM_KEY, JSON.stringify({ jobType: 'topic', topic: 'Interest rates' }));
    await mount();
    expect(savedForm().channelList).toBe('');

    await openChannels();
    expect(channelList()!.value).toBe('');
    expect(host.textContent).not.toContain(NOTE);
    expect(window.localStorage.getItem(OFFERED_KEY)).toBeNull();
    await unmount();

    // Not offered then, so still offered once the draft is gone.
    window.localStorage.removeItem(FORM_KEY);
    await mount();
    await openChannels();
    expect(channelList()!.value).toBe(FILLED);
  });

  it('any other setting makes it a draft, whatever tab it was saved on', async () => {
    window.localStorage.setItem(FORM_KEY, JSON.stringify({ jobType: 'channel', videosPerChannel: 25 }));
    await mount();
    expect(channelList()!.value).toBe('');
    expect(window.localStorage.getItem(OFFERED_KEY)).toBeNull();
  });

  it('is never filled over a template picked on the page', async () => {
    templates = [
      {
        id: 'tpl-1', name: 'My channels', description: null, job_type: 'channel', builtin: false, builtin_key: null,
        version: 1, parameters: { job_type: 'channel' }, problems: [], created_at: '', updated_at: '',
      },
    ];
    await mount();
    const picker = host.querySelector<HTMLSelectElement>('select[aria-label="Start from a template"]')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(picker, 'tpl-1');
      picker.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await flush();
    expect(channelList()!.value).toBe('');
    expect(window.localStorage.getItem(OFFERED_KEY)).toBeNull();
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
