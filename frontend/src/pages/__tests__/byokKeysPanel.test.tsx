/**
 * E-5.6 keys panel on /account/ai-models, rendered through AIModelsPage.
 *
 * Studio accounts see one row per provider a stored key is used for
 * (`byok.providers`), with whether a key is set and when it last changed.
 * A key goes out once in the PUT body; the field is emptied the moment Save
 * is pressed, and the key never reaches the DOM, React Query's caches, a
 * toast or the console. The field stays out of the browser's password
 * manager: `autocomplete="one-time-code"` and no <form> to submit. Other
 * tiers see the plan note and never call `/auth/credentials`. The "keys do
 * not last" note follows `byok.keys_persist`; a malformed key
 * (`byok.key_invalid`) turns saving off and says so instead. "Verify key" is a
 * paid request on the user's key, so it fires on the press alone, and its
 * answer stands only for the key it asked about.
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
  usePreferredDepth: () => null,
  useSetPreferredDepth: () => ({ mutate: () => undefined, isPending: false }),
}));

const byok: { current: { providers: string[]; keys_persist: boolean; key_invalid?: boolean } | undefined } = {
  current: undefined,
};
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
let verifyAnswer: () => Promise<{ data: { provider: string; result: string } }> = async () => ({
  data: { provider: 'openai', result: 'valid' },
});
const post = vi.fn(async (url: string) => {
  if (url === '/settings/llm/estimate') {
    return { data: { benchmark: null, per_use_case: [], totals: { cost_usd: 0, unknown_pricing_models: [] } } };
  }
  if (url.endsWith('/verify')) return verifyAnswer();
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

/** Press the form's Save button (there is no <form> to submit). */
async function submitForm() {
  const save = Array.from(host.querySelectorAll<HTMLButtonElement>('[data-byok-key-form] button')).find(
    (b) => b.textContent?.trim() === 'Save key',
  )!;
  await act(async () => save.click());
}

async function pressEnter(el: HTMLInputElement) {
  await act(async () => {
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
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
  verifyAnswer = async () => ({ data: { provider: 'openai', result: 'valid' } });
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

const verifyCalls = () => post.mock.calls.filter(([url]) => url.endsWith('/verify'));
const checkLine = (provider: string) => row(provider)!.querySelector('[data-byok-check]');

describe('verifying a stored key', () => {
  it('sends nothing to a provider until the button is pressed, and then once', async () => {
    await mount();
    expect(verifyCalls()).toEqual([]);
    await act(async () => rowButton('openai', 'Verify key')!.click());
    await flush();
    expect(verifyCalls()).toEqual([['/auth/credentials/openai/verify']]);
    expect(checkLine('openai')!.getAttribute('data-byok-check')).toBe('valid');
    expect(checkLine('openai')!.textContent).toContain('The provider accepted this key.');
  });

  it('does not check a key on saving it', async () => {
    await mount();
    act(() => rowButton('anthropic', 'Add key')!.click());
    await typeInto(keyField()!, PLACEHOLDER);
    await submitForm();
    await flush();
    expect(rowButton('anthropic', 'Verify key')).toBeDefined();
    expect(verifyCalls()).toEqual([]);
  });

  it('offers no check for a provider with no key stored', async () => {
    await mount();
    expect(rowButton('anthropic', 'Verify key')).toBeUndefined();
  });

  it.each([
    ['refused', 'Refused', 'The provider refused this key.'],
    ['unreachable', 'Not checked', 'nothing is known about it'],
    ['unreachable', 'Not checked', 'A key limited to certain models stays here'],
  ] as const)('says what a %s answer means', async (result, badge, words) => {
    verifyAnswer = async () => ({ data: { provider: 'openai', result } });
    await mount();
    await act(async () => rowButton('openai', 'Verify key')!.click());
    await flush();
    expect(checkLine('openai')!.getAttribute('data-byok-check')).toBe(result);
    expect(checkLine('openai')!.textContent).toContain(badge);
    expect(checkLine('openai')!.textContent).toContain(words);
  });

  it("shows the server's words when the check itself is refused", async () => {
    const refusal = new AxiosError('429', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 429,
      statusText: 'Too Many Requests',
      data: { detail: 'Too many requests. Please retry after the cooldown period.' },
      headers: {},
      config: { headers: new AxiosHeaders() },
    });
    verifyAnswer = async () => {
      throw refusal;
    };
    await mount();
    await act(async () => rowButton('openai', 'Verify key')!.click());
    await flush();
    expect(checkLine('openai')!.getAttribute('data-byok-check')).toBe('error');
    expect(checkLine('openai')!.textContent).toContain('Too many requests');
  });

  it('drops the answer once the key it was about has been replaced', async () => {
    await mount();
    await act(async () => rowButton('openai', 'Verify key')!.click());
    await flush();
    expect(checkLine('openai')).not.toBeNull();
    act(() => rowButton('openai', 'Replace key')!.click());
    await typeInto(keyField()!, PLACEHOLDER);
    await submitForm();
    await flush();
    expect(checkLine('openai')).toBeNull();
  });

  it('turns the check off while a malformed key means no stored key can be read', async () => {
    byok.current = { providers: ['anthropic', 'google', 'openai'], keys_persist: false, key_invalid: true };
    await mount();
    expect(rowButton('openai', 'Verify key')!.disabled).toBe(true);
  });
});

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

  it('keeps the key field out of the browser password manager', async () => {
    await mount();
    act(() => rowButton('anthropic', 'Add key')!.click());
    const field = keyField()!;
    expect(field.type).toBe('password');
    // Chromium ignores "off" on a password field, and "new-password" is
    // the sign-up signal that invites its generator and save prompt.
    expect(field.getAttribute('autocomplete')).toBe('one-time-code');
    // No form, so no form submission for the browser to detect.
    expect(field.closest('form')).toBeNull();
    expect(row('anthropic')!.querySelector('form')).toBeNull();
    const buttons = Array.from(row('anthropic')!.querySelectorAll('button'));
    expect(buttons.every((b) => b.getAttribute('type') === 'button')).toBe(true);
  });

  it('saves on Enter in the key field, once', async () => {
    await mount();
    act(() => rowButton('anthropic', 'Add key')!.click());
    await typeInto(keyField()!, PLACEHOLDER);
    await pressEnter(keyField()!);
    await flush();
    expect(put).toHaveBeenCalledTimes(1);
    expect(put.mock.calls[0][1]).toEqual({ secret: PLACEHOLDER, label: null });
    expect(keyField()).toBeNull();
    expect(everywhere()).not.toContain(PLACEHOLDER);
  });

  it('saves on Enter in the label field too', async () => {
    await mount();
    act(() => rowButton('google', 'Add key')!.click());
    await typeInto(keyField()!, PLACEHOLDER);
    const label = row('google')!.querySelectorAll('input')[1] as HTMLInputElement;
    await typeInto(label, 'home');
    await pressEnter(label);
    await flush();
    expect(put).toHaveBeenCalledTimes(1);
    expect(put.mock.calls[0][1]).toEqual({ secret: PLACEHOLDER, label: 'home' });
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
    expect(host.querySelector('[data-byok-invalid]')).toBeNull();
  });

  it('turns saving off and names the cause when BYOK_ENCRYPTION_KEY is malformed', async () => {
    byok.current = { providers: ['anthropic', 'google', 'openai'], keys_persist: false, key_invalid: true };
    await mount();
    const note = host.querySelector('[data-byok-invalid]');
    expect(note).not.toBeNull();
    expect(note!.textContent).toContain('BYOK_ENCRYPTION_KEY is set but is not a valid key');
    expect(note!.textContent).toContain('saving is turned off');
    // Not the "no key, temporary key" note: that cause would be wrong.
    expect(host.querySelector('[data-byok-ephemeral]')).toBeNull();
    expect(host.textContent).not.toContain('This install has no BYOK_ENCRYPTION_KEY');
    // No way to open the key field.
    expect(rowButton('anthropic', 'Add key')!.disabled).toBe(true);
    expect(rowButton('openai', 'Replace key')!.disabled).toBe(true);
    act(() => rowButton('anthropic', 'Add key')!.click());
    expect(keyField()).toBeNull();
    // Removing a stored key never touches the encryption key, so it stays.
    expect(rowButton('openai', 'Remove')!.disabled).toBe(false);
    await act(async () => rowButton('openai', 'Remove')!.click());
    await act(async () => anyButton('Remove key')!.click());
    await flush();
    expect(del).toHaveBeenCalledTimes(1);
  });

  it('shows the server reason inline when a save is refused for a malformed key', async () => {
    put.mockRejectedValueOnce(
      new AxiosError('Service Unavailable', 'ERR_BAD_RESPONSE', undefined, undefined, {
        status: 503,
        statusText: 'Service Unavailable',
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: {
          detail:
            "Keys cannot be saved: this install's BYOK_ENCRYPTION_KEY is set but is not a valid key. Ask the operator to fix it.",
        },
      }),
    );
    // Settings read before the operator broke the key: saving still offered.
    await mount();
    act(() => rowButton('google', 'Add key')!.click());
    await typeInto(keyField()!, PLACEHOLDER);
    await submitForm();
    await flush();
    expect(row('google')!.querySelector('[role="alert"]')!.textContent).toContain(
      'BYOK_ENCRYPTION_KEY is set but is not a valid key',
    );
    expect(keyField()!.value).toBe('');
    expect(everywhere()).not.toContain(PLACEHOLDER);
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
