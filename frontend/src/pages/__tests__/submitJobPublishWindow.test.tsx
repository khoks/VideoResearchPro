/**
 * S-8.6.3 and S-8.6.4 on the submit page: the publish-window control, the
 * template round trip through the real picker, and the two source-type
 * starters. What leaves the page is read from `useCreateJob`, the request the
 * server receives.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('../../hooks/useOnboarding', () => ({ useOnboarding: () => ({ data: undefined }) }));
const mutateAsync = vi.fn();
vi.mock('../../hooks/useJobs', () => ({ useCreateJob: () => ({ mutateAsync, isPending: false }) }));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../hooks/useCapability', () => ({ useCapability: () => false }));
vi.mock('../../hooks/useTierCapabilities', () => ({ useTierCapabilities: () => ({ tier: 'free', numVideosCap: 100 }) }));
let templates: JobTemplate[] = [];
const updateTemplate = vi.fn();
vi.mock('../../hooks/useJobTemplates', () => ({
  useJobTemplates: () => ({ data: templates }),
  useCreateTemplate: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useUpdateTemplate: () => ({ mutate: updateTemplate, mutateAsync: vi.fn(), isPending: false }),
  useDeleteTemplate: () => ({ mutate: vi.fn(), isPending: false }),
  useTemplateVersions: () => ({ data: [], isLoading: false }),
}));

import { SubmitJobPage } from '../SubmitJobPage';
import { useSystemStatusStore } from '../../stores/systemStatusStore';
import { summariseParameters } from '../TemplatesPage';
import type { JobTemplate, TemplateParameters } from '../../services/jobTemplatesApi';

const LABEL = 'Prefer sources from the last (days)';

const BASE: TemplateParameters = {
  job_type: 'topic',
  search_instructions: null,
  num_videos: 10,
  min_duration_minutes: null,
  max_duration_minutes: null,
  channel_type_filters: null,
  preferred_channels: null,
  output_length: null,
  visual_analysis: false,
  source_types: null,
  published_after_days: null,
  channel_list: null,
  videos_per_channel: null,
};

function template(over: Partial<JobTemplate> & { id: string; name: string }): JobTemplate {
  return {
    description: null,
    job_type: 'topic',
    builtin: false,
    builtin_key: null,
    version: 1,
    parameters: BASE,
    problems: [],
    created_at: '2026-11-04T00:00:00Z',
    updated_at: '2026-11-04T00:00:00Z',
    ...over,
  };
}

// As the migration seeds them (927718ee5b78).
const PODCAST_DIGEST = template({
  id: 'podcast',
  name: 'Podcast digest',
  builtin: true,
  builtin_key: 'podcast-digest',
  parameters: { ...BASE, num_videos: 8, output_length: 'brief', source_types: ['podcast_episode'] },
});
const DEBATE = template({
  id: 'debate',
  name: 'Mixed-source debate',
  builtin: true,
  builtin_key: 'mixed-source-debate',
  parameters: {
    ...BASE,
    num_videos: 18,
    source_types: ['video', 'hn_story', 'podcast_episode'],
    search_instructions: 'The live disagreements about {{topic}}.',
  },
});
const WEEKLY = template({
  id: 'weekly',
  name: 'Weekly scan',
  parameters: { ...BASE, published_after_days: 7 },
});

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/jobs/new']}>
          <SubmitJobPage />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const labelFor = (text: string) =>
  Array.from(host.querySelectorAll('label')).find((l) => l.textContent?.includes(text));
const windowInput = () => {
  const label = labelFor(LABEL);
  return label ? host.querySelector<HTMLInputElement>(`[id="${label.htmlFor}"]`) : null;
};
const topicInput = () => host.querySelector<HTMLInputElement>('input[placeholder^="e.g. Quantum"]')!;
const buttonLabelled = (text: string) =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim().startsWith(text)) as HTMLButtonElement;
const picker = () => host.querySelector<HTMLSelectElement>('select[aria-label="Start from a template"]')!;

function type(el: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

function pickTemplate(id: string) {
  const select = picker();
  act(() => {
    select.value = id;
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
  updateTemplate.mockReset();
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

describe('the publish-window control', () => {
  it('is empty by default and sends nothing, so an untouched form is the request it always was', async () => {
    await mount();
    expect(windowInput()!.value).toBe('');
    type(topicInput(), 'tariffs');
    await submit();
    expect(submitted()).not.toHaveProperty('published_after_days');
  });

  it('says it is a preference, not a filter', async () => {
    await mount();
    expect(host.textContent).toContain('A preference, not a filter');
  });

  it('sends the days as a number', async () => {
    await mount();
    type(topicInput(), 'tariffs');
    type(windowInput()!, '30');
    await submit();
    expect(submitted().published_after_days).toBe(30);
  });

  it('refuses a value the server would, in the form', async () => {
    await mount();
    type(topicInput(), 'tariffs');
    type(windowInput()!, '4000');
    await submit();
    expect(mutateAsync).not.toHaveBeenCalled();
    expect(host.textContent).toContain('from 1 to 3650');
  });

  it('survives a reload as part of the draft', async () => {
    await mount();
    type(windowInput()!, '14');
    act(() => root.unmount());
    root = createRoot(host);
    await mount();
    expect(windowInput()!.value).toBe('14');
  });

  it('only appears for topic research', async () => {
    await mount();
    act(() => buttonLabelled('Channels').click());
    await flush();
    expect(windowInput()).toBeNull();
  });

  it('goes when YouTube goes: only YouTube results are ranked', async () => {
    await mount();
    type(topicInput(), 'tariffs');
    type(windowInput()!, '30');
    act(() => buttonLabelled('Hacker News').click());
    await flush();
    expect(windowInput()).not.toBeNull();
    expect(host.textContent).toContain('Steers the YouTube results only.');

    act(() => buttonLabelled('YouTube').click());
    await flush();
    expect(windowInput()).toBeNull();
    await submit();
    expect(submitted()).not.toHaveProperty('published_after_days');
    expect(submitted().source_types).toEqual(['hn_story']);
  });

  it('comes back with YouTube, still holding what was typed', async () => {
    await mount();
    type(windowInput()!, '30');
    act(() => buttonLabelled('Hacker News').click());
    await flush();
    act(() => buttonLabelled('YouTube').click());
    await flush();
    act(() => buttonLabelled('YouTube').click());
    await flush();
    expect(windowInput()!.value).toBe('30');
  });
});

describe('template round trip', () => {
  it('fills the window from a template and submits it', async () => {
    templates = [WEEKLY];
    await mount();
    pickTemplate('weekly');
    await flush();
    expect(windowInput()!.value).toBe('7');
    type(topicInput(), 'tariffs');
    await submit();
    expect(submitted().published_after_days).toBe(7);
    expect(mutateAsync.mock.calls[0][0].provenance).toEqual({ templateId: 'weekly', templateVersion: 1 });
  });

  it('saves a changed window back as parameters', async () => {
    templates = [WEEKLY];
    await mount();
    pickTemplate('weekly');
    await flush();
    type(windowInput()!, '30');
    act(() => buttonLabelled('Save changes').click());
    await flush();
    expect(updateTemplate.mock.calls[0][0].body.parameters.published_after_days).toBe(30);
  });

  it('clears the window when the next template has none', async () => {
    templates = [WEEKLY, DEBATE];
    await mount();
    pickTemplate('weekly');
    await flush();
    pickTemplate('debate');
    await flush();
    expect(windowInput()!.value).toBe('');
  });
});

describe('source-type starters (S-8.6.4)', () => {
  it('lists both in the picker, under Starters', async () => {
    templates = [WEEKLY, DEBATE, PODCAST_DIGEST];
    await mount();
    const group = host.querySelector('optgroup[label="Starters"]')!;
    expect(Array.from(group.querySelectorAll('option')).map((o) => o.textContent)).toEqual([
      'Mixed-source debate · topic',
      'Podcast digest · topic',
    ]);
  });

  it('runs the podcast digest as a podcast search, with no window to offer', async () => {
    templates = [PODCAST_DIGEST];
    await mount();
    pickTemplate('podcast');
    await flush();
    expect(windowInput()).toBeNull();
    type(topicInput(), 'nuclear power');
    await submit();
    expect(submitted()).toMatchObject({
      topic: 'nuclear power',
      num_videos: 8,
      output_length: 'brief',
      source_types: ['podcast_episode'],
    });
    expect(submitted()).not.toHaveProperty('published_after_days');
  });

  it('runs the debate across its three sources', async () => {
    templates = [DEBATE];
    await mount();
    pickTemplate('debate');
    await flush();
    type(topicInput(), 'nuclear power');
    await submit();
    expect(submitted()).toMatchObject({
      num_videos: 18,
      source_types: ['video', 'hn_story', 'podcast_episode'],
    });
  });
});

describe('the template summary', () => {
  it('counts results, not videos, when a recipe searches other sources', () => {
    expect(summariseParameters(PODCAST_DIGEST.parameters)).toBe('8 results · Podcasts · brief report');
    expect(summariseParameters(DEBATE.parameters)).toBe('18 results · YouTube + Hacker News + Podcasts');
  });

  it('keeps "videos" for a YouTube recipe, and names a window', () => {
    expect(summariseParameters(BASE)).toBe('10 videos');
    expect(summariseParameters({ ...BASE, source_types: ['video'] })).toBe('10 videos');
    expect(summariseParameters(WEEKLY.parameters)).toBe('10 videos · prefers the last 7 days');
    expect(summariseParameters({ ...BASE, published_after_days: 1 })).toBe('10 videos · prefers the last day');
  });
});

describe('a source that refused this install (T-1.5.14.1)', () => {
  afterEach(() => useSystemStatusStore.setState({ capabilities: null, sourceHolds: {} }));

  it('is off the form, and the form says why', async () => {
    useSystemStatusStore.setState({
      capabilities: { bluesky_search_enabled: false },
      sourceHolds: { bluesky_post: { status: 403, until: '2026-11-05T12:00:00+00:00' } },
    });
    await mount();
    expect(host.querySelector('button[data-source-type="bluesky_post"]')).toBeNull();
    expect(host.querySelector('[data-testid="source-type-held-note"]')?.textContent).toContain(
      'Bluesky refused its last search',
    );
  });

  it('stays on offer while /health has not answered', async () => {
    useSystemStatusStore.setState({ capabilities: null, sourceHolds: {} });
    await mount();
    expect(host.querySelector('button[data-source-type="bluesky_post"]')).not.toBeNull();
  });

  it('can be tried anyway: the request carries it, and it says the source refused (T-1.5.14.6)', async () => {
    useSystemStatusStore.setState({
      capabilities: { bluesky_search_enabled: false },
      sourceHolds: { bluesky_post: { status: 403, until: '2026-11-05T12:00:00+00:00' } },
    });
    await mount();
    expect(host.querySelector('button[data-source-type="bluesky_post"]')).toBeNull();
    type(topicInput(), 'tariffs');

    act(() => buttonLabelled('Try Bluesky anyway').click());
    expect(host.querySelector('[data-testid="source-type-held-note"]')?.textContent).toContain(
      'Bluesky refused its last search from this install. This run tries it anyway',
    );
    await submit();

    expect(host.querySelector('[role="alert"]')).toBeNull();
    expect(submitted().source_types).toEqual(['video', 'bluesky_post']);
  });

  it('leaves it out of the request unless the reader asks', async () => {
    useSystemStatusStore.setState({
      capabilities: { bluesky_search_enabled: false },
      sourceHolds: { bluesky_post: { status: 403, until: '2026-11-05T12:00:00+00:00' } },
    });
    await mount();
    type(topicInput(), 'tariffs');

    await submit();

    expect(submitted()).not.toHaveProperty('source_types');
  });
});
