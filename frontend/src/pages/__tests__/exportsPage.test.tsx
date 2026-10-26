/**
 * T-8.8.1.5 at the production caller: every button on the Exports page
 * fetches its file with the bearer header (the axios client) and saves it
 * from a blob: URL. No URL anywhere carries the JWT.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const JWT = 'header.payload.signature';
const getMock = vi.fn<(path: string, config?: unknown) => Promise<{ data: Blob }>>(async () => ({ data: new Blob(['{}\n']) }));
vi.mock('../../services/api', () => ({
  default: {
    get: (path: string, config?: unknown) => getMock(path, config),
    defaults: { baseURL: 'http://localhost:8000/api/v1' },
  },
}));
let token: string | null = JWT;
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ token }) }));
vi.mock('../../hooks/useOnboarding', () => ({ useOnboarding: () => ({ data: { milestones: { questions: 3 } } }) }));

import { ExportsPage } from '../ExportsPage';
import { useJobStore } from '../../stores/jobStore';

let host: HTMLDivElement;
let root: Root;
let saved: Array<{ href: string; download: string }>;

async function flush() {
  for (let i = 0; i < 4; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

const buttons = () => Array.from(host.querySelectorAll('button'));

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  token = JWT;
  let n = 0;
  URL.createObjectURL = vi.fn(() => `blob:http://localhost:5173/e${++n}`);
  URL.revokeObjectURL = vi.fn();
  saved = [];
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    saved.push({ href: this.href, download: this.download });
  });
  getMock.mockClear();
  act(() => root.render(<ExportsPage />));
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

describe('ExportsPage', () => {
  it('fetches each of the six files with the header and saves it from a blob: URL', async () => {
    expect(buttons()).toHaveLength(6);
    for (let i = 0; i < 6; i++) {
      act(() => buttons()[i].click());
      await flush();
    }
    expect(getMock.mock.calls.map((c) => c[0])).toEqual([
      '/exports/qa-dataset/openai.jsonl',
      '/exports/qa-dataset/tuple.jsonl',
      '/exports/knowledge-dataset/openai.jsonl',
      '/exports/knowledge-dataset/tuple.jsonl',
      '/exports/notes.md',
      '/exports/notes.jsonl',
    ]);
    expect(getMock.mock.calls.every((c) => (c[1] as { responseType: string }).responseType === 'blob')).toBe(true);
    expect(saved.map((s) => s.download)).toEqual([
      'qa-dataset-openai.jsonl',
      'qa-dataset-tuple.jsonl',
      'knowledge-dataset-openai.jsonl',
      'knowledge-dataset-tuple.jsonl',
      'notes.md',
      'notes.jsonl',
    ]);
    for (const s of saved) {
      expect(s.href.startsWith('blob:')).toBe(true);
      expect(s.href).not.toContain(JWT);
    }
    for (const [path] of getMock.mock.calls) expect(path).not.toContain(JWT);
  });

  it('shows the fetch in progress on the clicked button only', async () => {
    let release: (v: { data: Blob }) => void = () => {};
    getMock.mockImplementationOnce(() => new Promise((r) => { release = r; }));
    act(() => buttons()[0].click());
    await flush();
    expect(buttons()[0].disabled).toBe(true);
    expect(buttons().slice(1).every((b) => b.disabled)).toBe(true);
    await act(async () => release({ data: new Blob(['x']) }));
    await flush();
    expect(buttons().every((b) => !b.disabled)).toBe(true);
    expect(saved).toHaveLength(1);
  });

  it('tells a signed-out visitor to sign in rather than fetching', async () => {
    token = null;
    act(() => root.render(<ExportsPage />));
    act(() => buttons()[0].click());
    await flush();
    expect(getMock).not.toHaveBeenCalled();
    expect(useJobStore.getState().toasts.some((t) => /signed in/i.test(t.message))).toBe(true);
  });
});
