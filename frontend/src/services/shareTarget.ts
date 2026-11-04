/*
 * The Android share target (T-3.7.6.1), page side.
 *
 * `public/share-target-sw.js` keeps each incoming share in the Cache API and
 * redirects to the page without it, so the shared words never sit in a URL.
 * This module reads what is waiting, turns it into the same `/echo/shares`
 * calls every other surface makes, and removes it. Waiting on the device is
 * also how a share survives a sign-in: nothing about it travels through the
 * redirect.
 *
 * What waits here is a proposal, not a request: any website can post a form to
 * the share target, and only the user's tap on the page says this one is theirs.
 * Nothing here posts on its own, and a delivery covers only the shares the user
 * was shown (`keys`), not whatever has arrived since.
 */
import type { AxiosError } from 'axios';
import { MAX_DROP_FILES } from '../utils/echoDrop';
import { parseQuickShareInput } from '../utils/echoShares';
import { detailFromErrorBody } from '../utils/ingestResults';
import { echoApi } from './echoApi';

/** The manifest's share target: the worker's whole scope, and never a page. */
const SHARE_TARGET_PATH = '/echo/share-target';
/** Where the worker sends a share. Outside its scope, so the page is not controlled. */
export const SHARE_REVIEW_PATH = '/echo/incoming';
const WORKER_URL = '/share-target-sw.js';
// Repeated in public/share-target-sw.js, which is served as it is.
const CACHE_NAME = 'echo-pending-shares-v1';
const STORED_AT_HEADER = 'x-stored-at';
const SENT_HEADER = 'x-sent-parts';
const SOURCE_TITLE_MAX = 300;

/** A share left waiting this long is dropped unread: whoever opens the app a
 * week later did not mean to send it now, and it should not stay on the device. */
export const PENDING_MAX_AGE_MS = 24 * 60 * 60 * 1000;

export interface PendingShare {
  key: string;
  title: string;
  text: string;
  url: string;
  files: File[];
  /** Indexes into the plan that have already reached the server. */
  sent: number[];
}

export type SharePart =
  | { kind: 'file'; file: File }
  | { kind: 'url'; url: string; title?: string }
  | { kind: 'text'; text: string; title?: string };

export type ShareDelivery =
  | { kind: 'nothing' }
  | { kind: 'added'; count: number; skipped: number }
  | { kind: 'refused'; count: number; refused: number; status: number; detail: string | null }
  | { kind: 'failed'; detail: string | null };

/** Makes the app ready to receive shares. Fails quietly: an insecure origin
 * or a browser with no service workers simply has no share target. */
export function registerShareTarget(): void {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register(WORKER_URL, { scope: SHARE_TARGET_PATH }).catch(() => undefined);
}

async function openStash(): Promise<Cache | null> {
  // No `caches` on an insecure origin; asking `has` first creates nothing.
  if (typeof caches === 'undefined') return null;
  try {
    return (await caches.has(CACHE_NAME)) ? await caches.open(CACHE_NAME) : null;
  } catch {
    return null;
  }
}

function field(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === 'string' ? value : '';
}

function sentParts(response: Response): number[] {
  return (response.headers.get(SENT_HEADER) ?? '').split(',').filter(Boolean).map(Number);
}

/** Everything waiting that is still wanted, oldest first. Stale or unreadable
 * entries are removed here, and so is one with nothing left to post: a form
 * with no fields, or a share that went in full and could not be removed. */
export async function readPendingShares(now: number = Date.now()): Promise<PendingShare[]> {
  const stash = await openStash();
  if (!stash) return [];
  const found: Array<PendingShare & { storedAt: number }> = [];
  for (const request of await stash.keys()) {
    const response = await stash.match(request);
    const storedAt = Number(response?.headers.get(STORED_AT_HEADER));
    if (!response || !storedAt || now - storedAt > PENDING_MAX_AGE_MS) {
      await stash.delete(request);
      continue;
    }
    try {
      const form = await response.formData();
      const item = {
        key: request.url,
        storedAt,
        title: field(form, 'title'),
        text: field(form, 'text'),
        url: field(form, 'url'),
        files: form.getAll('files').filter((f): f is File => f instanceof File && f.size > 0),
        sent: sentParts(response),
      };
      if (unsentParts(item).parts.length) found.push(item);
      else await stash.delete(request);
    } catch {
      await stash.delete(request);
    }
  }
  return found.sort((a, b) => a.storedAt - b.storedAt);
}

export async function hasPendingShares(): Promise<boolean> {
  try {
    return (await readPendingShares()).length > 0;
  } catch {
    return false;
  }
}

async function forgetPendingShare(key: string): Promise<void> {
  const stash = await openStash();
  await stash?.delete(key);
}

/** The user declined these. They leave the device unposted. */
export async function discardPendingShares(keys: string[]): Promise<void> {
  await Promise.all(keys.map(forgetPendingShare));
}

/** On sign-out: a waiting share carries no owner, so without this the next
 * person to sign in on this browser would be offered it. */
export async function clearPendingShares(): Promise<void> {
  try {
    if (typeof caches !== 'undefined') await caches.delete(CACHE_NAME);
  } catch {
    /* signing out must not depend on the Cache API */
  }
}

/** Remember on the device what has been posted, so that a reload, a retry or
 * a reopened app does not post it again. The whole entry is rewritten, which
 * is one atomic step of the Cache API. If it fails the worst case is one
 * share added twice. */
async function recordSent(key: string, sent: Set<number>): Promise<void> {
  try {
    const stash = await openStash();
    const stored = await stash?.match(key);
    if (!stash || !stored) return;
    const headers = new Headers(stored.headers);
    headers.set(SENT_HEADER, [...sent].join(','));
    await stash.put(key, new Response(await stored.blob(), { headers }));
  } catch {
    /* see above */
  }
}

/**
 * What one share becomes, as a drop would. Android apps put a link in `text`
 * as often as in `url`. Words sent beside a link are a share of their own
 * unless they only repeat it, and none of it counts as the user's own words:
 * the sharing app wrote it (D-089).
 */
export function planOsShare(pending: Pick<PendingShare, 'title' | 'text' | 'url' | 'files'>): {
  parts: SharePart[];
  skipped: number;
} {
  const parts: SharePart[] = pending.files.slice(0, MAX_DROP_FILES).map((file) => ({ kind: 'file', file }));
  const title = pending.title.trim().slice(0, SOURCE_TITLE_MAX) || undefined;
  const url = parseQuickShareInput(pending.url);
  const text = parseQuickShareInput(pending.text);
  if (url.kind === 'url') {
    parts.push({ kind: 'url', url: url.url, title });
    if (text.kind === 'text' && !text.text.includes(url.url)) parts.push({ kind: 'text', text: text.text, title });
  } else if (text.kind === 'url') {
    parts.push({ kind: 'url', url: text.url, title });
  } else if (text.kind === 'text') {
    parts.push({ kind: 'text', text: text.text, title });
  } else if (!parts.length && title) {
    parts.push({ kind: 'text', text: title });
  }
  return { parts, skipped: Math.max(0, pending.files.length - MAX_DROP_FILES) };
}

async function sendPart(part: SharePart): Promise<void> {
  if (part.kind === 'file') {
    await echoApi.uploadShare(part.file, { surface: 'os_share' });
  } else if (part.kind === 'url') {
    await echoApi.createShare({ url: part.url, surface: 'os_share', source_title: part.title });
  } else {
    await echoApi.createShare({ text: part.text, surface: 'os_share', source_title: part.title });
  }
}

/** What is left of a share to post, for showing and for sending. */
export function unsentParts(pending: PendingShare): { parts: SharePart[]; skipped: number } {
  const { parts, skipped } = planOsShare(pending);
  return { parts: parts.filter((_, index) => !pending.sent.includes(index)), skipped };
}

/** A refusal is the server's answer and will not change on a retry, so that
 * part is dropped (a file over the cap). Anything else may pass later, so the
 * share keeps waiting: a dropped connection, a server error, a rate limit, or
 * a session that ended, which sends the user to sign in. */
function refusedStatus(err: unknown): number | null {
  const status = (err as AxiosError).response?.status;
  if (status === undefined || status >= 500 || status === 401 || status === 429) return null;
  return status;
}

async function deliver(keys: string[], send: (part: SharePart) => Promise<void>): Promise<ShareDelivery> {
  const wanted = new Set(keys);
  const pending = (await readPendingShares()).filter((item) => wanted.has(item.key));
  if (!pending.length) return { kind: 'nothing' };
  let count = 0;
  let skipped = 0;
  let refused = 0;
  let first: { status: number; detail: string | null } | null = null;
  for (const item of pending) {
    const plan = planOsShare(item);
    skipped += plan.skipped;
    const sent = new Set(item.sent);
    for (const [index, part] of plan.parts.entries()) {
      if (sent.has(index)) continue;
      // A 403 is the whole account, so the rest would only hear it again.
      if (first?.status === 403) {
        refused += 1;
        continue;
      }
      try {
        await send(part);
      } catch (err) {
        const detail = detailFromErrorBody((err as AxiosError).response?.data) ?? null;
        const status = refusedStatus(err);
        if (status === null) return { kind: 'failed', detail };
        refused += 1;
        if (!first || status === 403) first = { status, detail };
        continue;
      }
      sent.add(index);
      await recordSent(item.key, sent);
    }
    count += sent.size;
    await forgetPendingShare(item.key);
  }
  return first ? { kind: 'refused', count, refused, ...first } : { kind: 'added', count, skipped };
}

let delivering: Promise<ShareDelivery> | null = null;

/** Post the shares the user was shown and agreed to. Each one leaves the
 * device once every part has been added or refused, and only then. A second
 * call while one runs joins it, so no share is posted twice. */
export function deliverPendingShares(keys: string[], send: (part: SharePart) => Promise<void> = sendPart): Promise<ShareDelivery> {
  delivering ??= deliver(keys, send).finally(() => {
    delivering = null;
  });
  return delivering;
}
