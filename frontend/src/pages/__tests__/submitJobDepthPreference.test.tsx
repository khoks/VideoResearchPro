/**
 * T-1.15.3.9 on the submit form. A blank form starts from the account's default
 * depth and sends it, because the select shows it. Everything else is unchanged:
 * Auto with no preference sends no `output_length`, a depth chosen on the page
 * wins, a duplicated run and a template bring their own, and a saved template
 * freezes only what the reader picked, because a preference is theirs alone.
 *
 * Mutation checks, run by hand on 2026-11-04:
 * - `handleSubmit` reading `form` fails "sends the preference";
 * - the select reading `form` fails "shows the preference";
 * - `withPreferredDepth` ignoring `depthChosen` fails "lets Auto win" and "a
 *   duplicated run";
 * - the select's `onChange` not setting `depthChosen` fails "lets Auto win";
 * - `saveFormAsTemplate` reading the preference fails "freezes nothing".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_FORM, isDraftForm, withPreferredDepth } from '../../utils/jobForm';
import type { Job } from '../../types/job';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('../../hooks/useOnboarding', () => ({ useOnboarding: () => ({ data: undefined }) }));
const mutateAsync = vi.fn();
vi.mock('../../hooks/useJobs', () => ({ useCreateJob: () => ({ mutateAsync, isPending: false }) }));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../hooks/useCapability', () => ({ useCapability: () => false }));
vi.mock('../../hooks/useTierCapabilities', () => ({ useTierCapabilities: () => ({ tier: 'free', numVideosCap: 100 }) }));
const createTemplate = vi.fn();
let templates: unknown[] = [];
vi.mock('../../hooks/useJobTemplates', () => ({
  useJobTemplates: () => ({ data: templates }),
  useCreateTemplate: () => ({ mutate: vi.fn(), mutateAsync: createTemplate, isPending: false }),
  useUpdateTemplate: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useDeleteTemplate: () => ({ mutate: vi.fn(), isPending: false }),
  useTemplateVersions: () => ({ data: [], isLoading: false }),
}));

import { SubmitJobPage } from '../SubmitJobPage';

let host: HTMLDivElement;
let root: Root;
let client: QueryClient;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(preferred: string | null, state?: unknown) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['auth', 'me'], { preferred_output_length: preferred });
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[{ pathname: '/jobs/new', state }]}>
          <SubmitJobPage />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const labelFor = (text: string) =>
  Array.from(host.querySelectorAll('label')).find((l) => l.textContent?.includes(text));
const depthField = () => host.querySelector<HTMLSelectElement>(`[id="${labelFor('Report depth')?.htmlFor}"]`)!;
const topicInput = () => host.querySelector<HTMLInputElement>('input[placeholder^="e.g. Quantum"]')!;

function type(el: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

function pickDepth(value: string) {
  const select = depthField();
  act(() => {
    select.value = value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

async function submit() {
  await act(async () => {
    host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}

const submitted = () => mutateAsync.mock.calls[0][0].data as Record<string, unknown>;

beforeEach(() => {
  window.localStorage.clear();
  mutateAsync.mockReset();
  mutateAsync.mockResolvedValue({ id: 'j1' });
  createTemplate.mockReset();
  templates = [];
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.localStorage.clear();
});

describe('SubmitJobPage: the account default depth', () => {
  it('stays on Auto and sends nothing for anyone who never set one', async () => {
    await mount(null);
    expect(depthField().value).toBe('auto');
    type(topicInput(), 'Tidal storage');
    await submit();
    expect('output_length' in submitted()).toBe(false);
  });

  it('shows the preference on a blank form', async () => {
    await mount('deep');
    expect(depthField().value).toBe('deep');
  });

  it('fills the form when the preference arrives after the first render', async () => {
    await mount(null);
    act(() => client.setQueryData(['auth', 'me'], { preferred_output_length: 'brief' }));
    await flush();
    expect(depthField().value).toBe('brief');
  });

  it('sends the preference, because the select shows it', async () => {
    await mount('deep');
    type(topicInput(), 'Tidal storage');
    await submit();
    expect(submitted().output_length).toBe('deep');
  });

  it('lets a depth picked on the page win', async () => {
    await mount('deep');
    pickDepth('brief');
    type(topicInput(), 'Tidal storage');
    await submit();
    expect(submitted().output_length).toBe('brief');
  });

  it('lets Auto win too: picking it sends nothing', async () => {
    await mount('deep');
    pickDepth('auto');
    expect(depthField().value).toBe('auto');
    type(topicInput(), 'Tidal storage');
    await submit();
    expect('output_length' in submitted()).toBe(false);
  });

  it('keeps a picked Auto through a reload of the draft', async () => {
    await mount('deep');
    pickDepth('auto');
    act(() => root.unmount());
    root = createRoot(host);
    await mount('deep');
    expect(depthField().value).toBe('auto');
  });

  it('copies a duplicated run left on Auto rather than applying the preference', async () => {
    const job = {
      id: 'j0',
      job_type: 'topic',
      topic: 'Tidal storage',
      num_videos: 10,
      output_length: null,
    } as unknown as Job;
    await mount('deep', { cloneFrom: job });
    expect(depthField().value).toBe('auto');
    await submit();
    expect('output_length' in submitted()).toBe(false);
  });

  it("copies a duplicated run's own depth", async () => {
    const job = {
      id: 'j0',
      job_type: 'topic',
      topic: 'Tidal storage',
      num_videos: 10,
      output_length: 'standard',
    } as unknown as Job;
    await mount('deep', { cloneFrom: job });
    expect(depthField().value).toBe('standard');
  });

  it('freezes nothing in a saved template: a preference is one person\'s', async () => {
    createTemplate.mockResolvedValue({
      id: 't1',
      name: 'Mine',
      version: 1,
      job_type: 'topic',
      problems: [],
      parameters: { job_type: 'topic' },
    });
    await mount('deep');
    type(topicInput(), 'Tidal storage');
    await act(async () => {
      Array.from(host.querySelectorAll('button'))
        .find((b) => b.textContent?.trim().startsWith('Save as template'))!
        .click();
    });
    await flush();
    const name = document.querySelector<HTMLInputElement>('[role="dialog"] input')!;
    type(name, 'Mine');
    await act(async () => {
      Array.from(document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'))
        .find((b) => /save/i.test(b.textContent ?? ''))!
        .click();
    });
    await flush();
    expect(createTemplate).toHaveBeenCalledTimes(1);
    expect(createTemplate.mock.calls[0][0].parameters.output_length ?? null).toBeNull();
  });
});

describe('withPreferredDepth', () => {
  it('leaves the stored form untouched, so an empty form is not a draft', () => {
    const shown = withPreferredDepth(DEFAULT_FORM, 'deep');
    expect(shown.outputLength).toBe('deep');
    expect(DEFAULT_FORM.outputLength).toBe('auto');
    expect(isDraftForm(DEFAULT_FORM)).toBe(false);
  });

  it('returns the form as it is with no preference', () => {
    expect(withPreferredDepth(DEFAULT_FORM, null)).toBe(DEFAULT_FORM);
  });

  it('never replaces a depth the form already holds', () => {
    const form = { ...DEFAULT_FORM, outputLength: 'brief' as const };
    expect(withPreferredDepth(form, 'deep')).toBe(form);
  });
});
