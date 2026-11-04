/**
 * /account/system: the health endpoints shown as a page.
 *
 * - `/health/llm`: one row per use case (provider, model, reasoning, result,
 *   latency), the error and the measured warnings beneath a row that has
 *   them, a filter to problems only, and the unavailable features.
 * - `/health/scheduler` and `/health/quota`, each failing on its own.
 * - The restart control exists only for an operator (`is_operator`) and
 *   posts `/admin/restart`; a refusal is shown, not swallowed.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AxiosError, AxiosHeaders } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeResponse } from '../../hooks/useMe';
import type { HealthLLMResponse, SchedulerStatus, YouTubeQuotaStatus } from '../../services/systemApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const me: { current: MeResponse | undefined } = { current: undefined };
vi.mock('../../hooks/useMe', () => ({
  useMe: () => ({ data: me.current, isLoading: false }),
}));

const waitForApi = vi.fn(async () => 'back' as const);
vi.mock('../../utils/waitForApi', () => ({ waitForApi: (...args: unknown[]) => waitForApi(...(args as [])) }));

const llmBody: { current: HealthLLMResponse } = { current: undefined as unknown as HealthLLMResponse };
const schedulerBody: SchedulerStatus = {
  enabled: true,
  tick_seconds: 300,
  lease_seconds: 600,
  grace_seconds: 30,
  kinds: ['echo_sync', 'saved_search'],
  rows: { total: 4, enabled: 3, due: 1, claimed: 0 },
  last_run_at: '2026-11-03T08:00:00Z',
};
const quotaBody: YouTubeQuotaStatus = { date: '2026-11-03', used: 1200, daily_limit: 10000, remaining: 8800 };

const failing = new Set<string>();
const get = vi.fn(async (url: string) => {
  if (failing.has(url)) throw new Error(`down: ${url}`);
  if (url === '/health/llm') return { data: llmBody.current };
  if (url === '/health/scheduler') return { data: schedulerBody };
  if (url === '/health/quota') return { data: quotaBody };
  throw new Error(`unexpected GET ${url}`);
});
const post = vi.fn(async (_url: string, _body: unknown, _config?: unknown) => ({
  data: { status: 'accepted', message: 'Restart scheduled in ~2s.', skip_frontend: true },
}));
vi.mock('../../services/api', () => ({
  default: {
    get: (url: string) => get(url),
    post: (url: string, body: unknown, config?: unknown) => post(url, body, config),
  },
}));

import { SystemStatusPage } from '../SystemStatusPage';

function probe(): HealthLLMResponse {
  return {
    summary: { status: 'degraded', unavailable_features: ['visual_analysis'], last_checked_at: 1762156800 },
    use_cases: {
      qa_formulate_answer: {
        provider: 'openai',
        model: 'gpt-test',
        reasoning: 'medium',
        ok: true,
        latency_ms: 812,
        error: null,
        guidance: { status: 'measured', decision_id: 'D-001' },
        warnings: [],
      },
      report_map_chunks: {
        provider: 'local',
        model: 'qwen-test',
        reasoning: 'off',
        ok: true,
        latency_ms: 95,
        error: null,
        warnings: [
          { kind: 'weaker', model: 'qwen-test', why: 'Dropped facts in the blind round.', decision_id: 'D-077' },
        ],
      },
      visual_describe_frame: {
        provider: 'google',
        model: 'gemini-test',
        reasoning: 'off',
        ok: false,
        latency_ms: 0,
        error: 'build: no provider key configured',
        warnings: [],
      },
    },
  };
}

let host: HTMLDivElement;
let root: Root;

function account(isOperator: boolean): MeResponse {
  return { id: 'u1', email: 'me@example.com', created_at: '2026-05-01T00:00:00', tier: 'studio', is_operator: isOperator };
}

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/account/system']}>
          <SystemStatusPage />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const section = (id: string) => host.querySelector<HTMLElement>(`[data-system-section="${id}"]`);
const useCaseRows = () =>
  Array.from(host.querySelectorAll('[data-use-case]')).map((el) => el.getAttribute('data-use-case'));
const button = (label: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as
    | HTMLButtonElement
    | undefined;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  me.current = account(false);
  llmBody.current = probe();
  failing.clear();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('AI models section', () => {
  it('shows every probed use case with provider, model, reasoning, result and latency', async () => {
    await mount();
    const llm = section('llm')!;
    expect(llm.textContent).toContain('Degraded');
    expect(useCaseRows()).toEqual(['qa_formulate_answer', 'report_map_chunks', 'visual_describe_frame']);
    const cells = Array.from(llm.querySelectorAll('[data-use-case="qa_formulate_answer"] td')).map((td) =>
      td.textContent?.trim(),
    );
    expect(cells).toEqual(['qa_formulate_answer', 'openai', 'gpt-test', 'medium', 'OK', '812 ms']);
    expect(llm.querySelector('[data-use-case="visual_describe_frame"]')!.textContent).toContain('Failed');
    expect(llm.querySelector('[data-llm-counts]')!.textContent).toBe('3 functions · 1 failed · 1 with a warning');
  });

  it('puts the error and the measured warnings beneath their rows', async () => {
    await mount();
    const failed = host.querySelector('[data-use-case-detail="visual_describe_frame"]')!;
    expect(failed.textContent).toContain('Error: build: no provider key configured');
    const warned = host.querySelector('[data-use-case-detail="report_map_chunks"]')!;
    expect(warned.textContent).toContain('Measured weaker than the default here (D-077).');
    expect(warned.textContent).toContain('Dropped facts in the blind round.');
    expect(host.querySelector('[data-use-case-detail="qa_formulate_answer"]')).toBeNull();
  });

  it('names the unavailable features', async () => {
    await mount();
    expect(section('llm')!.textContent).toContain('Unavailable: Visual analysis (frames).');
  });

  it('filters to failures and warnings', async () => {
    await mount();
    const toggle = section('llm')!.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    act(() => toggle.click());
    expect(useCaseRows()).toEqual(['report_map_chunks', 'visual_describe_frame']);
  });

  it('says when no probe has run', async () => {
    llmBody.current = { summary: { status: 'unknown', unavailable_features: [], last_checked_at: null }, use_cases: {} };
    await mount();
    expect(section('llm')!.textContent).toContain('Not probed yet');
    expect(section('llm')!.textContent).toContain('No probe has run in this API process yet.');
    expect(host.querySelector('[data-llm-table]')).toBeNull();
  });
});

describe('scheduler and quota sections', () => {
  it('shows the scheduler configuration and row counts', async () => {
    await mount();
    const s = section('scheduler')!;
    expect(s.textContent).toContain('On');
    expect(s.textContent).toContain('5 min');
    expect(s.textContent).toContain('4 (3 enabled)');
    expect(s.textContent).toContain('echo_sync, saved_search');
    expect(s.textContent).toContain('10 min / 30 s');
  });

  it("shows today's YouTube quota with a meter", async () => {
    await mount();
    const q = section('quota')!;
    expect(q.querySelector('[data-quota-line]')!.textContent).toBe(
      '1,200 of 10,000 units used on 2026-11-03 (UTC), 8,800 left.',
    );
    const meter = q.querySelector('[role="meter"]')!;
    expect(meter.getAttribute('aria-valuenow')).toBe('1200');
    expect(meter.getAttribute('aria-valuemax')).toBe('10000');
  });

  it('keeps the other sections when one endpoint fails', async () => {
    failing.add('/health/scheduler');
    await mount();
    expect(section('scheduler')!.textContent).toContain('Try again');
    expect(section('quota')!.querySelector('[data-quota-line]')).not.toBeNull();
    expect(useCaseRows()).toHaveLength(3);
  });
});

describe('wiring', () => {
  const raw = (pattern: Record<string, string>) => Object.values(pattern)[0];

  it('is routed at /account/system and linked from the account menu and the palette', () => {
    const routes = raw(
      import.meta.glob('../../routes/index.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
    );
    expect(routes).toMatch(/path: 'account\/system', \.\.\.lazyPage\(<SystemStatusPage \/>/);
    const layout = raw(
      import.meta.glob('../../layouts/AppLayout.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
    );
    const account = layout.slice(layout.indexOf('<NavGroup label="Account">'));
    expect(account).toMatch(/onNavigatePath\('\/account\/system'\)[^]*?System status/);
    const palette = raw(
      import.meta.glob('../../components/palette/PalettePanel.tsx', { query: '?raw', import: 'default', eager: true }) as Record<
        string,
        string
      >,
    );
    expect(palette).toContain("nav('system', 'System status', '/account/system'");
  });
});

describe('restart control', () => {
  it('is not offered to an account that does not operate the install', async () => {
    me.current = account(false);
    await mount();
    expect(section('restart')).toBeNull();
    expect(button('Restart services')).toBeUndefined();
    expect(post).not.toHaveBeenCalled();
  });

  it('is not offered while is_operator is missing', async () => {
    me.current = { id: 'u1', email: 'me@example.com', created_at: '2026-05-01T00:00:00', tier: 'studio' };
    await mount();
    expect(section('restart')).toBeNull();
  });

  it('restarts for an operator after a confirmation, keeping the frontend by default', async () => {
    me.current = account(true);
    await mount();
    expect(section('restart')).not.toBeNull();
    act(() => button('Restart services')!.click());
    expect(document.querySelector('[role="dialog"]')!.textContent).toContain('Restart every service?');
    expect(post).not.toHaveBeenCalled();
    await act(async () => button('Restart now')!.click());
    await flush();
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0][0]).toBe('/admin/restart');
    expect(post.mock.calls[0][2]).toEqual({ params: { skip_frontend: true } });
    expect(waitForApi).toHaveBeenCalledTimes(1);
    expect(host.querySelector('[data-restart-status]')!.getAttribute('data-restart-status')).toBe('back');
  });

  it('restarts the frontend too when the operator unticks the box', async () => {
    me.current = account(true);
    await mount();
    const keep = section('restart')!.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    act(() => keep.click());
    act(() => button('Restart services')!.click());
    expect(document.querySelector('[role="dialog"]')!.textContent).toContain('this page may reload');
    await act(async () => button('Restart now')!.click());
    await flush();
    expect(post.mock.calls[0][2]).toEqual({ params: { skip_frontend: false } });
  });

  it("shows the server's refusal", async () => {
    me.current = account(true);
    post.mockRejectedValueOnce(
      new AxiosError('Not Implemented', 'ERR_BAD_RESPONSE', undefined, undefined, {
        status: 501,
        statusText: 'Not Implemented',
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: { detail: 'Self-restart is only wired up for Windows hosts today.' },
      }),
    );
    await mount();
    act(() => button('Restart services')!.click());
    await act(async () => button('Restart now')!.click());
    await flush();
    const status = host.querySelector('[data-restart-status]')!;
    expect(status.getAttribute('data-restart-status')).toBe('failed');
    expect(status.textContent).toBe('Self-restart is only wired up for Windows hosts today.');
    expect(waitForApi).not.toHaveBeenCalled();
  });
});
