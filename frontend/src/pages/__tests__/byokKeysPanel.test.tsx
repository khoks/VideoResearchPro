/**
 * E-5.6 keys panel on /account/ai-models, rendered through AIModelsPage.
 *
 * Studio accounts see one row per provider a stored key is used for
 * (`byok.providers`), with whether a key is set and when it last changed.
 * A key goes out once in the PUT body; the field is emptied the moment the
 * form submits, and the key never reaches the DOM, React Query's caches, a
 * toast or the console. Other tiers see the plan note and never call
 * `/auth/credentials`. The "keys do not last" note follows
 * `byok.keys_persist`.
 *
 * The "key" below is a placeholder, not key material.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AxiosError, AxiosHeaders } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeResponse } from '../../hooks/useMe';
import type { CredentialMetadata } from '../../services/credentialsApi';
import { useJobStore } from '../../stores/jobStore';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const PLACEHOLDER = 'placeholder-not-a-key-91c2';

const me: { current: MeResponse | undefined } = { current: undefined };
vi.mock('../../hooks/useMe', () => ({
  useMe: () => ({ data: me.current, isLoading: false }),
  useInvalidateMe: () => async () => undefined,
}));

const byok: { current: { providers: string[]; keys_persist: boolean } | undefined } = { current: undefined };
let stored: CredentialMetadata[] = [];

function settingsBody() {
  return {
    use_cases: [
      {
        use_case: 'qa_formulate_answer',
        summary: 'Final answer',
        group: 'Job Q&A',
        default: { provider: 'openai', model: 'gpt-test', reasoning: 'off' },
        override: null,
        effective: { provider: 'openai', model: 'gpt-test', reasoning: 'off' },
        typical_input_tokens: 1,
        typical_output_tokens: 1,
        guidance: {
          status: 'unmeasured',
          decision_id: null,
          decided_on: null,
          flagship_delta: '',
          downgrade_risk: '',
          measured_cost: '',
          model_verdicts: [],
          related_decisions: [],
          note: '',
        },
        vision: false,
      },
    ],
    providers: { openai: { models: [{ id: 'gpt-test', context_window: 1000 }] } },
    reasoning_levels: ['off'],
    vision_capable_models: [],
    ...(byok.current ? { byok: byok.current } : {}),
  };
}

const get = vi.fn(async (url: string) => {
  if (url === '/settings/llm') return { data: settingsBody() };
  if (url === '/auth/credentials') return { data: stored.map((k) => ({ ...k })) };
  throw new Error(`unexpected GET ${url}`);
});
const post = vi.fn(async (url: string) => {
  if (url === '/settings/llm/estimate') {
    return { data: { benchmark: null, per_use_case: [], totals: { cost_usd: 0, unknown_pricing_models: [] } } };
  }
  throw new Error(`unexpected POST ${url}`);
});
const put = vi.fn(async (url: string, body: { secret: string; label: string | null }) => {
  const provider = url.split('/').pop()!;
  const row: CredentialMetadata = {
    provider,
    label: body.label,
    created_at: '2026-11-03T09:00:00',
    updated_at: '2026-11-03T09:30:00',
    has_secret: true,
  };
  stored = [...stored.filter((k) => k.provider !== provider), row];
  return { data: row };
});
const del = vi.fn(async (url: string) => {
  const provider = url.split('/').pop()!;
  const before = stored.length;
  stored = stored.filter((k) => k.provider !== provider);
  return { data: { deleted: stored.length < before } };
});
vi.mock('../../services/api', () => ({
  default: {
    get: (url: string) => get(url),
    post: (url: string) => post(url),
    put: (url: string, body: { secret: string; label: string | null }) => put(url, body),
    delete: (url: string) => del(url),
  },
}));

import { AIModelsPage } from '../AIModelsPage';

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;

function account(tier: MeResponse['tier']): MeResponse {
  return { id: 'u1', email: 'me@example.com', created_at: '2026-05-01T00:00:00', tier, is_operator: false };
}

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount() {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/account/ai-models']}>
          <AIModelsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const row = (provider: string) => host.querySelector<HTMLElement>(`[data-byok-provider="${provider}"]`);
const rowButton = (provider: string, label: string) =>
  Array.from(row(provider)?.querySelectorAll('button') ?? []).find((b) => b.textContent?.trim() === label) as
    | HTMLButtonElement
    | undefined;
const keyField = () => host.querySelector<HTMLInputElement>('[data-byok-panel] input[type="password"]');
const anyButton = (label: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as
    | HTMLButtonElement
    | undefined;

async function typeInto(el: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function submitForm() {
  const form = keyField()!.closest('form')!;
  await act(async () => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
}

/** Everything the panel could have left the key in, as one string. */
function everywhere(): string {
  const queries = qc.getQueryCache().getAll().map((q) => q.state.data);
  const mutations = qc.getMutationCache().getAll().map((m) => m.state.variables);
  return [
    document.body.innerHTML,
    JSON.stringify(queries),
    JSON.stringify(mutations),
    JSON.stringify(useJobStore.getState().toasts),
  ].join('\n');
}

type ConsoleSpy = { mock: { calls: unknown[][] }; mockRestore: () => void };
let consoleSpies: ConsoleSpy[] = [];

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  me.current = account('studio');
  byok.current = { providers: ['anthropic', 'google', 'openai'], keys_persist: true };
  stored = [
    {
      provider: 'openai',
      label: 'work',
      created_at: '2026-11-01T10:00:00',
      updated_at: '2026-11-02T15:45:00',
      has_secret: true,
    },
  ];
  useJobStore.setState({ toasts: [] });
  consoleSpies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) =>
    vi.spyOn(console, m).mockImplementation(() => undefined),
  );
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  for (const s of consoleSpies) s.mockRestore();
  vi.clearAllMocks();
});

function consoleSawPlaceholder(): boolean {
  return consoleSpies.some((s) => s.mock.calls.some((args: unknown[]) => JSON.stringify(args).includes(PLACEHOLDER)));
}

describe('keys panel for a Studio account', () => {
  it('lists each provider a key is used for, with whether it is set and when it changed', async () => {
    await mount();
    const providers = Array.from(host.querySelectorAll('[data-byok-provider]')).map((el) =>
      el.getAttribute('data-byok-provider'),
    );
    expect(providers).toEqual(['anthropic', 'google', 'openai']);
    expect(row('openai')!.textContent).toContain('Key set');
    expect(row('openai')!.textContent).toContain('work');
    // Zone-less server time read as UTC, not local time.
    const expected = new Date('2026-11-02T15:45:00Z').toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
    expect(row('openai')!.querySelector('[data-byok-status]')!.textContent).toBe(`Last changed ${expected}`);
    expect(row('anthropic')!.textContent).toContain('Not set');
    expect(row('anthropic')!.textContent).toContain("Your calls use the install's key.");
    // No row for the local endpoint, and the panel says why.
    expect(row('local')).toBeNull();
    expect(host.textContent).toContain('so it takes no key here');
    expect(get).toHaveBeenCalledWith('/auth/credentials');
  });

  it('sends a new key once in the PUT body and empties the field the moment it submits', async () => {
    let release: () => void = () => undefined;
    put.mockImplementationOnce(async (_url, body) => {
      await new Promise<void>((r) => {
        release = r;
      });
      const row: CredentialMetadata = {
        provider: 'anthropic',
        label: body.label,
        created_at: '2026-11-03T09:00:00',
        updated_at: '2026-11-03T09:30:00',
        has_secret: true,
      };
      stored = [...stored, row];
      return { data: row };
    });
    await mount();
    act(() => rowButton('anthropic', 'Add key')!.click());
    const field = keyField()!;
    expect(field.type).toBe('password');
    expect(field.getAttribute('autocomplete')).toBe('off');
    await typeInto(field, `  ${PLACEHOLDER}\n`);
    await submitForm();

    // The request is in flight: the field is already empty.
    expect(keyField()!.value).toBe('');
    expect(put).toHaveBeenCalledTimes(1);
    expect(put.mock.calls[0][0]).toBe('/auth/credentials/anthropic');
    expect(put.mock.calls[0][1]).toEqual({ secret: PLACEHOLDER, label: null });

    await act(async () => release());
    await flush();
    expect(keyField()).toBeNull();
    expect(row('anthropic')!.textContent).toContain('Key set');
    expect(useJobStore.getState().toasts.some((t) => t.kind === 'success')).toBe(true);
    expect(everywhere()).not.toContain(PLACEHOLDER);
    expect(consoleSawPlaceholder()).toBe(false);
    expect(put).toHaveBeenCalledTimes(1);
  });

  it('keeps the label when replacing a key', async () => {
    await mount();
    act(() => rowButton('openai', 'Replace key')!.click());
    const inputs = Array.from(row('openai')!.querySelectorAll('input'));
    expect(inputs.map((i) => i.value)).toEqual(['', 'work']);
    await typeInto(keyField()!, PLACEHOLDER);
    await submitForm();
    await flush();
    expect(put.mock.calls[0][1]).toEqual({ secret: PLACEHOLDER, label: 'work' });
  });

  it('shows a refusal inline, leaves the field empty and keeps the key out of everything', async () => {
    put.mockRejectedValueOnce(
      new AxiosError('Bad Request', 'ERR_BAD_REQUEST', undefined, undefined, {
        status: 400,
        statusText: 'Bad Request',
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: { detail: 'Key is too long (at most 2048 characters).' },
      }),
    );
    await mount();
    act(() => rowButton('google', 'Add key')!.click());
    await typeInto(keyField()!, PLACEHOLDER);
    await submitForm();
    await flush();
    expect(row('google')!.querySelector('[role="alert"]')!.textContent).toBe(
      'Key is too long (at most 2048 characters).',
    );
    expect(keyField()!.value).toBe('');
    expect(row('google')!.textContent).toContain('Not set');
    expect(everywhere()).not.toContain(PLACEHOLDER);
    expect(consoleSawPlaceholder()).toBe(false);
  });

  it('does not send an empty key', async () => {
    await mount();
    act(() => rowButton('google', 'Add key')!.click());
    await typeInto(keyField()!, '   ');
    await submitForm();
    await flush();
    expect(put).not.toHaveBeenCalled();
    expect(row('google')!.querySelector('[role="alert"]')!.textContent).toBe('Paste a key first.');
  });

  it('removes a key after a confirmation', async () => {
    await mount();
    act(() => rowButton('openai', 'Remove')!.click());
    const dialog = document.querySelector('[role="dialog"]')!;
    expect(dialog.textContent).toContain('Remove your OpenAI key?');
    expect(dialog.textContent).toContain("go back to the install's key");
    await act(async () => anyButton('Remove key')!.click());
    await flush();
    expect(del).toHaveBeenCalledTimes(1);
    expect(del.mock.calls[0][0]).toBe('/auth/credentials/openai');
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(row('openai')!.textContent).toContain('Not set');
  });

  it('lists a stored key no call reads as not used, so it can be removed', async () => {
    stored.push({
      provider: 'local',
      label: null,
      created_at: '2026-11-01T10:00:00',
      updated_at: '2026-11-01T10:00:00',
      has_secret: true,
    });
    await mount();
    expect(row('local')!.textContent).toContain('Not used');
    expect(rowButton('local', 'Remove')).toBeTruthy();
    expect(rowButton('local', 'Add key')).toBeUndefined();
  });

  it('says keys do not last when the install has no BYOK_ENCRYPTION_KEY', async () => {
    byok.current = { providers: ['anthropic', 'google', 'openai'], keys_persist: false };
    await mount();
    const note = host.querySelector('[data-byok-ephemeral]');
    expect(note).not.toBeNull();
    expect(note!.textContent).toContain('BYOK_ENCRYPTION_KEY');
    expect(note!.textContent).toContain('stops working when the server restarts');
  });

  it('shows no such note when stored keys persist', async () => {
    await mount();
    expect(host.querySelector('[data-byok-ephemeral]')).toBeNull();
  });

  it('lists only the providers the server names', async () => {
    byok.current = { providers: ['openai'], keys_persist: true };
    await mount();
    const providers = Array.from(host.querySelectorAll('[data-byok-provider]')).map((el) =>
      el.getAttribute('data-byok-provider'),
    );
    expect(providers).toEqual(['openai']);
  });
});

describe('keys panel below Studio', () => {
  it.each(['free', 'pro'] as const)('shows the plan note on %s and never asks for keys', async (tier) => {
    me.current = account(tier);
    await mount();
    expect(host.querySelector('[data-byok-locked]')).not.toBeNull();
    expect(host.querySelector('[data-byok-panel]')).toBeNull();
    expect(get.mock.calls.map((c) => c[0])).not.toContain('/auth/credentials');
    expect(host.textContent).toContain('On the Studio plan you can add your own');
  });
});
