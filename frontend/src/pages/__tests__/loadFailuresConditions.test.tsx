/**
 * T-3.4.1.26: the readers that say a failed load only at times, checked both
 * ways round under the app's own query client.
 *
 * A reader passes `inlineErrors` as a condition when its line shows only on one
 * step, beside one other read, or for one kind of output, and `'load'` when its
 * line shows only in place of a first load. The guard
 * (`services/__tests__/oneToastPerFailure.test.ts`) counts any value but a
 * literal `false` as standing aside, so the condition itself is checked here:
 * when it holds, the line says the failure and the toast stands aside; when it
 * does not, the toast says it and no line does. Each line gives the server's
 * words, else its own sentence, and nothing for a 401.
 *
 * Mutation checks, run on 2026-11-10: `useMfaStatus({ inlineErrors: true })` on
 * the two-step card fails "during setup"; `{ inlineErrors: 'load' }` on the
 * knowledge drawer fails its "extraction reported down" rows, and
 * `{ inlineErrors: true }` there its failed refresh; `{ inlineErrors: true }` on
 * the models page's estimate fails both rows where the cost panel is not shown;
 * `{ inlineErrors: true }` on the studio's estimate fails the deck's rows;
 * `queryErrorsMeta(true)` on the palette fails "with actions still listed", and
 * the status's old failure clause fails both palette groups; `ERRORS_SHOWN_HERE`
 * in place of `LOAD_ERRORS_SHOWN_HERE` on the report peek fails its refresh row,
 * as it does on the library map and, as `{ inlineErrors: true }`, on the Echo
 * page's readiness. Dropping each option fails that reader's rows where its line
 * shows.
 *
 * The guard lists every file with such a reader (`CONDITIONAL_READERS`) and the
 * test that checks it, this file for most.
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CreateOutputPayload } from '../../services/authorApi';
import { createQueryClient } from '../../services/queryClient';
import { MFA_KEY } from '../../hooks/useAccountSecurity';
import {
  FAILURE_KINDS,
  SERVER_WORDS,
  clearToasts,
  failures,
  flush,
  press,
  toastMessages,
  type FailureKind,
} from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// The API, one answer per route, steered per test
// ---------------------------------------------------------------------------

type Answer = () => Promise<unknown>;
const routes = new Map<string, Answer>();
const ok = (data: unknown): Answer => async () => ({ data });
const fail = (kind: FailureKind): Answer => () => Promise.reject(failures[kind]());

function call(method: string, url: string): Promise<unknown> {
  const answer = routes.get(`${method} ${url}`);
  if (!answer) return Promise.reject(new Error(`unexpected ${method} ${url}`));
  return answer();
}

vi.mock('../../services/api', () => ({
  default: {
    get: (url: string) => call('GET', url),
    post: (url: string) => call('POST', url),
  },
}));

const author = {
  estimate: vi.fn<(p: CreateOutputPayload) => Promise<unknown>>(),
};
vi.mock('../../services/authorApi', () => ({
  authorApi: {
    listKinds: async () => ({ available: ['book', 'deck'], supported: ['book', 'deck'], formats: {} }),
    listOutputs: async () => [],
    listKnowledgeSources: async () => [],
    estimateOutput: (p: CreateOutputPayload) => author.estimate(p),
  },
}));

const features: Record<string, boolean> = {};
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: (name: string) => features[name] ?? true }));
vi.mock('../../hooks/useTierCapabilities', () => ({
  useTierCapabilities: () => ({ has: () => true, tier: 'pro', isLoading: false }),
}));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));
vi.mock('../../hooks/useJobs', () => ({
  useJobs: () => ({
    isLoading: false,
    data: [
      {
        id: 'job-1', topic: 'Smoking and lungs', job_type: 'topic', status: 'completed', has_report: true,
        video_count: 3, created_at: '2026-10-19T10:00:00', channel_list: [],
      },
    ],
  }),
}));
vi.mock('../../hooks/useShelves', () => ({ useShelves: () => ({ isLoading: false, data: [] }) }));
vi.mock('../../hooks/useOutputProgress', () => ({ useOutputsProgress: () => undefined }));
vi.mock('../../components/author/NewsletterCard', () => ({ NewsletterCard: () => null }));
vi.mock('../../components/account/ByokKeysPanel', () => ({ ByokKeysPanel: () => null }));
vi.mock('../../components/account/DepthPreferenceCard', () => ({ DepthPreferenceCard: () => null }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));
vi.mock('../../components/qa/SuggestionCard', () => ({ SuggestionCard: () => null }));
vi.mock('../../components/frames/VideoFramesPanel', () => ({ VideoFramesPanel: () => null }));

const echo = { status: vi.fn<() => Promise<unknown>>() };
vi.mock('../../services/echoApi', () => ({
  echoApi: {
    status: () => echo.status(),
    listConnectors: async () => ({ connectors: [], supported_kinds: [], items: [] }),
    listFactTombstones: async () => ({ items: [] }),
    listContext: async () => [],
  },
}));
vi.mock('../../components/echo/EchoDataCard', () => ({ EchoDataCard: () => null }));
vi.mock('../../components/echo/ShareTokensCard', () => ({ ShareTokensCard: () => null }));
vi.mock('../../components/echo/SignalsPanel', () => ({ SignalsPanel: () => null }));
vi.mock('../../components/echo/SpeakAsMePanel', () => ({ SpeakAsMePanel: () => null }));
vi.mock('../../components/echo/ActivityTimeline', () => ({ ActivityTimeline: () => null }));
vi.mock('../../components/echo/ConnectorsPanel', () => ({ ConnectorsPanel: () => null }));
vi.mock('../../components/echo/ReadinessDomains', () => ({ ReadinessDomains: () => null }));
// WebGL, which jsdom lacks; the table view stands in for it.
vi.mock('../../components/graph/GraphCanvas', () => ({ GraphCanvas: () => null }));

import { TwoStepCard } from '../../components/security/TwoStepCard';
import { VideoKnowledgeDrawer } from '../VideoKnowledgePage';
import { AIModelsPage } from '../AIModelsPage';
import { AuthorPage } from '../AuthorPage';
import PalettePanel from '../../components/palette/PalettePanel';
import { ReportPeekModal } from '../../components/jobs/ReportPeekModal';
import { EchoPage } from '../EchoPage';
import { GraphExplorer } from '../../components/graph/GraphExplorer';
import { DEFAULT_EXPLORER_STATE } from '../../components/graph/GraphControls';

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

let host: HTMLDivElement;
let root: Root;

async function mount(node: ReactNode, path = '/', client: QueryClient = createQueryClient()) {
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="*" element={node} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

/** Lets a failed first try reach its one retry, a second later, and settle. */
async function settle() {
  await flush();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  await flush();
}

/** A refresh of `queryKey`, as a window focus or a write elsewhere would ask. */
async function refresh(client: QueryClient, queryKey: readonly unknown[]) {
  act(() => {
    void client.invalidateQueries({ queryKey });
  });
  await settle();
}

// Dialogs render outside the host, so the whole document is read.
const text = () => document.body.textContent ?? '';
const count = (haystack: string, needle: string) => haystack.split(needle).length - 1;

/** What the global toast says for a failure: the server's words, else axios's,
 * and nothing for a 401 (`globalErrorToastMessage`). */
function toastFor(kind: FailureKind): string[] {
  return {
    words: [SERVER_WORDS],
    noWords: ['Request failed with status code 500'],
    noAnswer: ['Network Error'],
    sessionEnded: [],
  }[kind];
}

/** One message for a failed load: no toast, and the line once, with the
 * server's words or the reader's sentence; for a 401, neither. */
function expectSaidOnce(kind: FailureKind, fallback: string) {
  expect(toastMessages()).toEqual([]);
  if (kind === 'sessionEnded') {
    expect(text()).not.toContain(fallback);
    expect(text()).not.toContain('Not authenticated');
    return;
  }
  expect(count(text(), kind === 'words' ? SERVER_WORDS : fallback)).toBe(1);
  expect(text()).not.toMatch(/Network Error|status code 500/);
}

/** The failure is the toast's alone: it says it, and no line does. */
function expectToastAlone(kind: FailureKind, fallback: string) {
  expect(toastMessages()).toEqual(toastFor(kind));
  expect(text()).not.toContain(fallback);
  expect(text()).not.toContain(SERVER_WORDS);
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  routes.clear();
  author.estimate.mockReset();
  echo.status.mockReset();
  for (const name of Object.keys(features)) delete features[name];
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// The two-step card: its status line shows only while no setup step is open
// ---------------------------------------------------------------------------

describe('the two-step card', () => {
  const FALLBACK = 'Could not read whether two-step verification is on.';

  it.each(FAILURE_KINDS)('says a failed status read once, with no setup step open (%s)', async (kind) => {
    routes.set('GET /auth/mfa/status', fail(kind));
    await mount(<TwoStepCard />);
    await settle();
    expectSaidOnce(kind, FALLBACK);
  });

  it.each(FAILURE_KINDS)('during setup, where the key stays in place of the status line, leaves a failed refresh to the toast (%s)', async (kind) => {
    routes.set('GET /auth/mfa/status', ok({ enabled: false }));
    routes.set('POST /auth/mfa/enroll', ok({ secret: 'PLACEHOLDERNOTAKEY', provisioning_uri: 'otpauth://totp/placeholder' }));
    const client = createQueryClient();
    await mount(<TwoStepCard />, '/', client);
    await settle();
    await press('Set up two-step verification');
    expect(host.querySelector('[data-secret]')).not.toBeNull();
    routes.set('GET /auth/mfa/status', fail(kind));
    await refresh(client, MFA_KEY);
    expectToastAlone(kind, FALLBACK);
    expect(host.querySelector('[data-secret]')).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The knowledge drawer: its line shows only while extraction is on, in place of a report
// ---------------------------------------------------------------------------

describe('the knowledge drawer', () => {
  const FALLBACK = "Couldn't load the knowledge report. Try generating it again.";
  const ARTIFACT = {
    topics: ['tidal storage'],
    concepts: [],
    events: [],
    facts: [],
    knowledge_report_md: 'Tidal storage, in brief.',
    knowledge_extracted_at: '2026-11-04T00:00:00Z',
    output_length: null,
  };
  const drawer = <VideoKnowledgeDrawer videoId="doc-1" videoTitle="A talk" onClose={() => undefined} />;

  it.each(FAILURE_KINDS)('says a failed read once while extraction is on (%s)', async (kind) => {
    routes.set('GET /videos/doc-1/knowledge', fail(kind));
    await mount(drawer);
    await settle();
    expectSaidOnce(kind, FALLBACK);
  });

  it.each(FAILURE_KINDS)('with extraction reported down, shows no line, so the toast says it (%s)', async (kind) => {
    features.knowledge_extraction = false;
    routes.set('GET /videos/doc-1/knowledge', fail(kind));
    await mount(drawer);
    await settle();
    expectToastAlone(kind, FALLBACK);
  });

  it('keeps the toast for a refresh that fails behind a report on screen', async () => {
    routes.set('GET /videos/doc-1/knowledge', ok(ARTIFACT));
    const client = createQueryClient();
    await mount(drawer, '/', client);
    await settle();
    expect(text()).toContain('Tidal storage, in brief.');
    routes.set('GET /videos/doc-1/knowledge', fail('noWords'));
    await refresh(client, ['knowledge', 'doc-1']);
    expectToastAlone('noWords', FALLBACK);
    expect(text()).toContain('Tidal storage, in brief.');
  });
});

// ---------------------------------------------------------------------------
// The models page: the cost panel, and so its line, shows only beside the settings
// ---------------------------------------------------------------------------

describe('the AI models page', () => {
  const FALLBACK = 'The estimate service is unreachable right now. Model changes still save — only this preview is affected.';
  const SETTINGS_FALLBACK = 'We could not reach the settings service.';
  const settings = (useCases: number) => ({
    use_cases: Array.from({ length: useCases }, () => ({
      use_case: 'qa_formulate_answer',
      summary: 'Final answer',
      group: 'Job Q&A',
      default: { provider: 'openai', model: 'gpt-test', reasoning: 'off' },
      override: null,
      effective: { provider: 'openai', model: 'gpt-test', reasoning: 'off' },
      typical_input_tokens: 1,
      typical_output_tokens: 1,
      guidance: {
        status: 'unmeasured', decision_id: null, decided_on: null, flagship_delta: '', downgrade_risk: '',
        measured_cost: '', model_verdicts: [], related_decisions: [], note: '',
      },
      vision: false,
    })),
    providers: { openai: { models: [{ id: 'gpt-test', context_window: 1000 }] } },
    reasoning_levels: ['off'],
    vision_capable_models: [],
  });

  it.each(FAILURE_KINDS)('says a failed estimate once in the cost panel beside the settings (%s)', async (kind) => {
    routes.set('GET /settings/llm', ok(settings(1)));
    routes.set('POST /settings/llm/estimate', fail(kind));
    await mount(<AIModelsPage />);
    await settle();
    expect(text()).toContain('Final answer');
    expectSaidOnce(kind, FALLBACK);
  });

  it('when the settings fail too, the page says theirs and the toast says the estimate’s', async () => {
    routes.set('GET /settings/llm', fail('words'));
    routes.set('POST /settings/llm/estimate', fail('noWords'));
    await mount(<AIModelsPage />);
    await settle();
    expect(toastMessages()).toEqual(['Request failed with status code 500']);
    expect(count(text(), SERVER_WORDS)).toBe(1);
    expect(text()).not.toContain(SETTINGS_FALLBACK);
    expect(text()).not.toContain(FALLBACK);
  });

  it('with no use case listed, there is no cost panel, so a failed estimate keeps its toast', async () => {
    routes.set('GET /settings/llm', ok(settings(0)));
    routes.set('POST /settings/llm/estimate', fail('noWords'));
    await mount(<AIModelsPage />);
    await settle();
    expect(text()).toContain('No configurable model use cases were returned.');
    expectToastAlone('noWords', FALLBACK);
  });
});

// ---------------------------------------------------------------------------
// The studio's create dialog: only a book's framing says a failed estimate
// ---------------------------------------------------------------------------

describe("the studio's create dialog", () => {
  const FALLBACK = 'Could not estimate the cost.';

  const tick = async (label: string) => {
    const box = Array.from(document.querySelectorAll('label'))
      .find((l) => l.textContent?.includes(label))
      ?.querySelector('input') as HTMLInputElement;
    await act(async () => box.click());
    await flush();
  };

  it.each(FAILURE_KINDS)("says a failed estimate once beside a book's framing (%s)", async (kind) => {
    author.estimate.mockImplementation(() => Promise.reject(failures[kind]()));
    await mount(<AuthorPage />, '/author?new=book');
    await tick('Smoking and lungs');
    await tick('Light');
    await settle();
    expect(author.estimate).toHaveBeenCalledWith(expect.objectContaining({ kind: 'book', parameters: { cohesion: 'light' } }));
    expectSaidOnce(kind, FALLBACK);
  });

  it.each(FAILURE_KINDS)("leaves a deck's failed estimate to the toast, since a deck shows no line (%s)", async (kind) => {
    author.estimate.mockImplementation(() => Promise.reject(failures[kind]()));
    await mount(<AuthorPage />, '/author?new=deck');
    await tick('Smoking and lungs');
    await settle();
    expect(author.estimate).toHaveBeenCalledWith(expect.objectContaining({ kind: 'deck' }));
    expectToastAlone(kind, FALLBACK);
  });
});

// ---------------------------------------------------------------------------
// The palette: the list says a failed search only when no action matches either
// ---------------------------------------------------------------------------

describe('the command palette', () => {
  const FALLBACK = 'Search is unavailable right now.';

  beforeEach(() => {
    // jsdom has no layout: cmdk measures its list and scrolls the active option.
    Element.prototype.scrollIntoView ??= function scrollIntoView() {};
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    window.localStorage.clear();
  });

  async function typeQuery(value: string) {
    const input = document.querySelector<HTMLInputElement>('[role="dialog"] input')!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    // Past the debounce, then the failed try, its retry a second later, and the settle.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    await settle();
  }

  const options = () => Array.from(document.querySelectorAll('[role="option"]'));
  const status = () => document.querySelector('.reader-sr-only[aria-live]')?.textContent ?? '';

  it.each(FAILURE_KINDS)('with actions still listed, leaves a failed search to the toast, and the status counts what is listed (%s)', async (kind) => {
    routes.set('GET /search', fail(kind));
    await mount(<PalettePanel onClose={() => undefined} />);
    await typeQuery('theme');
    const listed = options().length;
    expect(listed).toBeGreaterThan(0);
    expect(toastMessages()).toEqual(toastFor(kind));
    // One voice: the toast speaks, so the palette's live status does not say it too.
    expect(status()).toBe(`${listed} ${listed === 1 ? 'result' : 'results'}`);
    expect(text()).not.toContain('unavailable');
    expect(text()).not.toContain(SERVER_WORDS);
    expect(document.querySelector('[role="dialog"] [role="alert"]')).toBeNull();
  });

  it.each(FAILURE_KINDS)('with nothing listed, says a failed search once, in the list, and the toast stands aside (%s)', async (kind) => {
    routes.set('GET /search', fail(kind));
    await mount(<PalettePanel onClose={() => undefined} />);
    await typeQuery('zzzz');
    expect(options()).toHaveLength(0);
    expectSaidOnce(kind, FALLBACK);
    // One voice here too: the line is the alert, and the live status is quiet.
    expect(status()).toBe('');
    expect(text()).not.toContain('actions still work');
    const alert = document.querySelector('[role="dialog"] [role="alert"]');
    if (kind === 'sessionEnded') expect(alert).toBeNull();
    else expect(alert?.textContent).toBe(kind === 'words' ? SERVER_WORDS : FALLBACK);
  });
});

// ---------------------------------------------------------------------------
// The report peek: its line shows only in place of a first load ('load')
// ---------------------------------------------------------------------------

describe('the report peek', () => {
  const FALLBACK = 'Could not load the report.';
  const REPORT = '<!DOCTYPE html><html><head><title>R</title></head><body><h1>R</h1></body></html>';

  beforeEach(() => {
    let made = 0;
    URL.createObjectURL = vi.fn(() => `blob:http://localhost:5173/r${++made}`);
    URL.revokeObjectURL = vi.fn();
  });

  it.each(FAILURE_KINDS)('says a failed first read once, in place of the frame (%s)', async (kind) => {
    routes.set('GET /jobs/job-1/report', fail(kind));
    await mount(<ReportPeekModal jobId="job-1" onClose={() => undefined} />);
    await settle();
    expectSaidOnce(kind, FALLBACK);
  });

  it('keeps the toast for a refresh that fails behind a framed report', async () => {
    routes.set('GET /jobs/job-1/report', ok(REPORT));
    const client = createQueryClient();
    await mount(<ReportPeekModal jobId="job-1" onClose={() => undefined} />, '/', client);
    await settle();
    expect(host.querySelector('iframe')).not.toBeNull();
    routes.set('GET /jobs/job-1/report', fail('noWords'));
    await refresh(client, ['reportDocument', 'job-1']);
    expectToastAlone('noWords', FALLBACK);
    expect(host.querySelector('iframe')).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The Echo page's readiness: its line shows only in place of a first read ('load')
// ---------------------------------------------------------------------------

describe("the Echo page's readiness", () => {
  const FALLBACK = "Couldn't read Echo's status.";
  const STATUS = {
    ready: false,
    total_rows: 40,
    distinct_sources: 1,
    has_personality_trait: false,
    threshold_total: 100,
    threshold_sources: 3,
  };

  it.each(FAILURE_KINDS)('says a failed first read once, in place of readiness (%s)', async (kind) => {
    echo.status.mockImplementation(() => Promise.reject(failures[kind]()));
    await mount(<EchoPage />, '/echo');
    await settle();
    expectSaidOnce(kind, FALLBACK);
  });

  it('keeps the toast for a refresh that fails behind readiness on screen', async () => {
    echo.status.mockResolvedValue(STATUS);
    const client = createQueryClient();
    await mount(<EchoPage />, '/echo', client);
    await settle();
    expect(text()).toContain("You're on the way.");
    echo.status.mockImplementation(() => Promise.reject(failures.noWords()));
    await refresh(client, ['echo', 'status']);
    expectToastAlone('noWords', FALLBACK);
    expect(text()).toContain("You're on the way.");
  });
});

// ---------------------------------------------------------------------------
// The library map: its line shows only in place of a first load ('load')
// ---------------------------------------------------------------------------

describe('the library map', () => {
  const FALLBACK = 'Try again in a moment.';
  // The table view: jsdom has no width to pick a view by.
  const STATE = { ...DEFAULT_EXPLORER_STATE, view: 'table' as const };
  const counts = { documents: 0, channels: 0, topics: 0, exchanges: 0 };
  const EMPTY = { nodes: [], edges: [], truncated: false, total: counts, shown: counts, summary: 'An empty library, mapped.', focus: null };
  const map = <GraphExplorer state={STATE} onChange={() => undefined} />;

  it.each(FAILURE_KINDS)('says a failed first load once, in place of the map (%s)', async (kind) => {
    routes.set('GET /library/graph', fail(kind));
    await mount(map);
    await settle();
    expectSaidOnce(kind, FALLBACK);
    if (kind !== 'sessionEnded') expect(count(text(), 'The map did not load')).toBe(1);
  });

  it('keeps the toast for a refresh that fails behind the map on screen', async () => {
    routes.set('GET /library/graph', ok(EMPTY));
    const client = createQueryClient();
    await mount(map, '/', client);
    await settle();
    expect(text()).toContain('An empty library, mapped.');
    routes.set('GET /library/graph', fail('noWords'));
    await refresh(client, ['libraryGraph']);
    expectToastAlone('noWords', FALLBACK);
    expect(text()).toContain('An empty library, mapped.');
    expect(text()).not.toContain('The map did not load');
  });
});
