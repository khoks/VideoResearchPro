/**
 * The failures a "one toast" test (T-3.4.1.15, T-3.4.1.17) puts through a
 * mutation, as axios hands them over, and what the reader then sees. A page
 * answers each with exactly one toast: the server's words when it sent any,
 * the page's own sentence when it sent none, and nothing for a 401, which the
 * session-expiry path owns.
 */
import { act } from 'react';
import { AxiosError, AxiosHeaders } from 'axios';
import { useJobStore } from '../../stores/jobStore';

export const SERVER_WORDS = 'The server says no, in words.';

function answered(status: number, data: unknown): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_REQUEST', undefined, undefined, {
    status, statusText: String(status), headers, config: { headers }, data,
  });
}

export const failures = {
  /** A refusal that says why, as most do (a 409, 403 or 429 with a `detail`). */
  words: () => answered(409, { detail: SERVER_WORDS }),
  /** A 500 with an HTML or plain body: axios says "Request failed with status code 500". */
  noWords: () => answered(500, 'Internal Server Error'),
  /** No answer at all: axios says "Network Error". */
  noAnswer: () => new AxiosError('Network Error', 'ERR_NETWORK'),
  /** The session ended, here or on another request. */
  sessionEnded: () => answered(401, { detail: 'Not authenticated' }),
};

export type FailureKind = keyof typeof failures;

/** What a failure of each kind should leave on screen, for a page whose own sentence is `fallback`. */
export function expectedToasts(kind: FailureKind, fallback: string): string[] {
  if (kind === 'sessionEnded') return [];
  return [kind === 'words' ? SERVER_WORDS : fallback];
}

export const FAILURE_KINDS: FailureKind[] = ['words', 'noWords', 'noAnswer', 'sessionEnded'];

export function toastMessages(): string[] {
  return useJobStore.getState().toasts.map((t) => t.message);
}

export function clearToasts(): void {
  useJobStore.setState({ toasts: [] });
}

export async function flush(): Promise<void> {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

/** Every button in the document (modals render outside the host) with this exact text. */
export function buttonsLabelled(label: string): HTMLButtonElement[] {
  return Array.from(document.querySelectorAll('button')).filter((b) => b.textContent?.trim() === label);
}

export async function press(label: string, which: 'first' | 'last' = 'first'): Promise<void> {
  const all = buttonsLabelled(label);
  const b = which === 'first' ? all[0] : all[all.length - 1];
  if (!b) throw new Error(`No button labelled "${label}"`);
  await act(async () => b.click());
  await flush();
}

export function typeInto(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  act(() => {
    Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
