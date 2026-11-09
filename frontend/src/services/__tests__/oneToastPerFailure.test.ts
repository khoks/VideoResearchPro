/**
 * One toast per failure (D-148 point 5, T-3.4.1.15, T-3.4.1.17).
 *
 * `toastMutationError` is what a hook says when it answers its own failures:
 * the server's words, else the page's sentence, and nothing for a 401.
 *
 * The sweep found 33 places in 12 files where a page or component toasted a
 * failed mutation from its own `mutate` call while the global handler toasted it
 * too. Each now lives in its hook. The guard below reads every module in `src`
 * but the tests, and fails on a new one: an error toast in a
 * per-call `onError` (written inline, or through a local helper), in the `catch`
 * after a `mutateAsync`, or in a component's own `useMutation` `onError` with no
 * `meta`. Such a toast is also lost once the component unmounts, and runs for the
 * last `mutate` of an observer only.
 *
 * Mutation checks, run on 2026-11-09: putting back the Echo page's old revoke
 * `onError`, SignalsPanel's `failed(...)` helper or SubscriptionPage's mutation
 * without `meta`, or moving a hook's toast back onto the `mutate` call of the
 * voice test, the importer or the data card, each fails the guard.
 *
 * A second guard below holds T-3.4.1.18's rule: a failure said on the page, where
 * the reader acted, needs its hook's `meta`, so the global toast does not say it
 * again.
 */
import { AxiosError, AxiosHeaders } from 'axios';
import { beforeEach, describe, expect, it } from 'vitest';
import { ERRORS_SHOWN_HERE, toastMutationError } from '../queryClient';
import { useJobStore } from '../../stores/jobStore';
import { SERVER_WORDS, clearToasts, failures, toastMessages } from './failures';

beforeEach(clearToasts);

describe('toastMutationError', () => {
  it('says the server’s words when it sent any', () => {
    toastMutationError(failures.words(), 'Our sentence.');
    expect(toastMessages()).toEqual([SERVER_WORDS]);
  });

  it('says the page’s sentence for a failure with no words, not axios’s', () => {
    toastMutationError(failures.noWords(), 'Our sentence.');
    toastMutationError(failures.noAnswer(), 'Our sentence.');
    expect(toastMessages()).toEqual(['Our sentence.', 'Our sentence.']);
  });

  it('reads a quota refusal’s message and a validation list', () => {
    const headers = new AxiosHeaders();
    const answered = (status: number, data: unknown) =>
      new AxiosError('x', 'ERR_BAD_REQUEST', undefined, undefined, { status, statusText: '', headers, config: { headers }, data });
    toastMutationError(answered(429, { detail: { resource: 'documents', message: 'Your library is full.' } }), 'Our sentence.');
    toastMutationError(answered(422, { detail: [{ msg: 'Value error, too long' }] }), 'Our sentence.');
    expect(toastMessages()).toEqual(['Your library is full.', 'too long']);
  });

  it('says nothing of a 401, which the session-expiry path owns', () => {
    toastMutationError(failures.sessionEnded(), 'Our sentence.');
    expect(useJobStore.getState().toasts).toEqual([]);
  });

  it('comes with the meta the global handler stands aside for', () => {
    expect(ERRORS_SHOWN_HERE).toEqual({ errorsShownHere: true });
  });
});

// ---------------------------------------------------------------------------
// The guard
// ---------------------------------------------------------------------------

/** Index just past the bracket that closes the one at `open`, skipping strings,
 * template literals and comments. */
function closing(src: string, open: number): number {
  const pairs: Record<string, string> = { '(': ')', '{': '}', '[': ']' };
  const stack: string[] = [];
  let i = open;
  while (i < src.length) {
    const ch = src[i];
    const next = src[i + 1];
    if (ch === '/' && next === '/') {
      i = src.indexOf('\n', i);
      if (i === -1) return src.length;
      continue;
    }
    if (ch === '/' && next === '*') {
      i = src.indexOf('*/', i + 2) + 2;
      continue;
    }
    if (ch === "'" || ch === '"') {
      i += 1;
      while (i < src.length && src[i] !== ch) i += src[i] === '\\' ? 2 : 1;
      i += 1;
      continue;
    }
    if (ch === '`') {
      i += 1;
      while (i < src.length && src[i] !== '`') {
        if (src[i] === '\\') i += 2;
        else if (src[i] === '$' && src[i + 1] === '{') i = closing(src, i + 1);
        else i += 1;
      }
      i += 1;
      continue;
    }
    if (pairs[ch]) stack.push(pairs[ch]);
    else if (ch === ')' || ch === '}' || ch === ']') {
      stack.pop();
      if (stack.length === 0) return i + 1;
    }
    i += 1;
  }
  return src.length;
}

const ERROR_TOAST = /pushToast\(\s*['"]error['"]|toastMutationError\(/;

/** An `onError` value says an error toast: inline, or through a local function
 * the file defines (`onError: fail`, `onError: (e) => failed(e, '...')`). */
function toastsInOnError(src: string, value: string): boolean {
  if (ERROR_TOAST.test(value)) return true;
  for (const name of value.match(/\b[A-Za-z_$][\w$]*(?=\s*\(|\s*$)/g) ?? []) {
    const def = new RegExp(`(?:const|let|function)\\s+${name.replace('$', '\\$')}\\b`).exec(src);
    if (def && ERROR_TOAST.test(src.slice(def.index, def.index + 400))) return true;
  }
  return false;
}

/** The text of an `onError:` property's value inside `args`, up to the next
 * top-level comma or the end of the object. */
function onErrorValues(args: string): string[] {
  const values: string[] = [];
  const re = /\bonError\s*:/g;
  for (let m = re.exec(args); m; m = re.exec(args)) {
    let i = m.index + m[0].length;
    const start = i;
    while (i < args.length) {
      const ch = args[i];
      if (ch === '(' || ch === '{' || ch === '[') i = closing(args, i);
      else if (ch === ',' || ch === '}' || ch === ')') break;
      else i += 1;
    }
    values.push(args.slice(start, i));
  }
  return values;
}

function lineOf(src: string, index: number): number {
  return src.slice(0, index).split('\n').length;
}

/** Every place in `src` where a failed mutation is toasted outside its hook. */
function doubleToasts(src: string): number[] {
  const found: number[] = [];
  // A per-call `onError` on `mutate` / `mutateAsync`.
  for (const m of src.matchAll(/\.(mutate|mutateAsync)\(/g)) {
    const open = m.index! + m[0].length - 1;
    const args = src.slice(open, closing(src, open));
    if (onErrorValues(args).some((v) => toastsInOnError(src, v))) found.push(lineOf(src, m.index!));
  }
  // The `catch` of a `try` that awaits a `mutateAsync`.
  for (const m of src.matchAll(/\btry\s*\{/g)) {
    const open = m.index! + m[0].length - 1;
    const end = closing(src, open);
    if (!src.slice(open, end).includes('.mutateAsync(')) continue;
    const handler = /^\s*catch\s*(\([^)]*\))?\s*\{/.exec(src.slice(end));
    if (!handler) continue;
    const catchOpen = end + handler[0].length - 1;
    if (ERROR_TOAST.test(src.slice(catchOpen, closing(src, catchOpen)))) found.push(lineOf(src, m.index!));
  }
  // `.mutateAsync(...).then(...).catch(...)`.
  for (const m of src.matchAll(/\.mutateAsync\(/g)) {
    let i = closing(src, m.index! + m[0].length - 1);
    for (let chained = /^\s*\.(then|catch|finally)\(/.exec(src.slice(i)); chained; chained = /^\s*\.(then|catch|finally)\(/.exec(src.slice(i))) {
      const open = i + chained[0].length - 1;
      const close = closing(src, open);
      if (chained[1] === 'catch' && ERROR_TOAST.test(src.slice(open, close))) found.push(lineOf(src, m.index!));
      i = close;
    }
  }
  // A component's own `useMutation` whose `onError` toasts without `meta`.
  for (const m of src.matchAll(/\buseMutation\(\s*\{/g)) {
    const open = m.index! + m[0].length - 1;
    const options = src.slice(open, closing(src, open));
    if (/\bmeta\s*:/.test(options)) continue;
    if (onErrorValues(options).some((v) => toastsInOnError(src, v))) found.push(lineOf(src, m.index!));
  }
  return found;
}

describe('the guard', () => {
  const sources = import.meta.glob(['../../**/*.{ts,tsx}', '!**/__tests__/**', '!**/*.test.{ts,tsx}'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;

  it('reads every page, component and hook, and the mutations in them', () => {
    const files = Object.keys(sources);
    expect(files.some((f) => f.endsWith('/pages/EchoPage.tsx'))).toBe(true);
    expect(files.some((f) => f.endsWith('/components/echo/VoiceTestPanel.tsx'))).toBe(true);
    expect(files.some((f) => f.endsWith('/hooks/useEcho.ts'))).toBe(true);
    const calls = Object.values(sources).reduce((n, src) => n + (src.match(/\.(mutate|mutateAsync)\(/g)?.length ?? 0), 0);
    expect(calls).toBeGreaterThan(60);
  });

  it('finds no module that toasts a failed mutation beside the global handler', () => {
    const offenders = Object.entries(sources)
      .map(([file, src]) => [file.replace('../../', 'src/'), doubleToasts(src)] as const)
      .filter(([, lines]) => lines.length > 0)
      .map(([file, lines]) => `${file}:${lines.join(',')}`);
    expect(offenders).toEqual([]);
  });

  it.each([
    ["x.mutate(id, { onError: () => pushToast('error', 'Revoke failed.') });"],
    ["x.mutate(id, {\n  onSuccess: () => ok(),\n  onError: (err) =>\n    pushToast(\n      'error',\n      'No.',\n    ),\n});"],
    ["const failed = (err, f) => pushToast('error', f);\nx.mutate(p, { onSuccess: done, onError: (e) => failed(e, 'No.') });"],
    ["const fail = (err) => pushToast('error', 'No.');\nx.mutate(p, { onSuccess: done, onError: fail });"],
    ["async function go() {\n  try {\n    await x.mutateAsync(p);\n  } catch (err) {\n    pushToast('error', 'No.');\n  }\n}"],
    ["x.mutateAsync(p).then(() => go()).catch((e) => pushToast('error', 'No.'));"],
    ["const m = useMutation({ mutationFn: f, onError: (err) => { pushToast('error', 'No.'); } });"],
  ])('catches %s', (src) => {
    expect(doubleToasts(src)).toHaveLength(1);
  });

  it.each([
    ["x.mutate(id, { onSuccess: () => pushToast('success', 'Done.') });"],
    ["x.mutate(id, { onError: (err) => setError(apiErrorMessage(err, 'No.')) });"],
    ["const fail = (err) => setError('No.');\nx.mutate(p, { onSuccess: done, onError: fail });"],
    ["try {\n  await x.mutateAsync(p);\n} catch {\n  // the global toast said it\n}\ntry { await y(); } catch { pushToast('error', 'No.'); }"],
    ["const m = useMutation({ mutationFn: f, onError: (err) => toastMutationError(err, 'No.'), meta: ERRORS_SHOWN_HERE });"],
  ])('leaves alone %s', (src) => {
    expect(doubleToasts(src)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// The second guard: a line on the page stands alone (T-3.4.1.18)
// ---------------------------------------------------------------------------
//
// A page that says a failed mutation where the reader acted (a line under the
// row, a turn in the Echo bubble) needs the global toast to stand aside, or the
// one failure is said twice. So the hook behind it sets `meta: ERRORS_SHOWN_HERE`:
// always, when every caller has such a line, or through an option the caller
// passes, when its callers differ (D-153 point 2).
//
// "Says it on the page" is read from the handler: a per-call `onError`, the
// `catch` of a `try` that awaits a `mutateAsync`, or a `.mutateAsync().catch()`
// that hands its error to a call that is not an `is…` check, or gives a setter a
// sentence. A handler that only checks the error (`isSessionEnded(err)`) or
// ignores it leaves the global toast to speak, as it should. Mutations passed in
// as props, which the guard cannot follow to their hook, are not read.
//
// Mutation checks, run on 2026-11-09: taking `meta` off `useDeleteTag`,
// `useDeleteShelf`, `useDeleteTemplate` or `useCompleteConnector`, or dropping
// `{ inlineErrors: true }` from the Echo bubble's `useAskLibraryQA`, each fails
// "finds no line on a page that the global toast repeats", naming that file.

/** How each mutation hook the app defines sets `meta`: always, only when a
 * caller passes its option, or never. */
type MetaWhen = 'always' | 'option' | 'never';

function metaWhen(options: string): MetaWhen {
  const meta = /\bmeta\s*:\s*([^,\n}]+)/.exec(options);
  if (!meta) return 'never';
  return meta[1].includes('?') ? 'option' : 'always';
}

function mutationHooks(sources: Record<string, string>): Map<string, MetaWhen> {
  const hooks = new Map<string, MetaWhen>();
  for (const src of Object.values(sources)) {
    const starts = [...src.matchAll(/export function (use\w+)\s*\(/g)];
    starts.forEach((m, k) => {
      const body = src.slice(m.index!, starts[k + 1]?.index ?? src.length);
      const call = /\buseMutation\(\s*\{/.exec(body);
      if (!call) return;
      const open = call.index + call[0].length - 1;
      hooks.set(m[1], metaWhen(body.slice(open, closing(body, open))));
    });
  }
  return hooks;
}

/** Whether a handler says its failure on the page. `handler` is the `onError`
 * value, a `catch (e) {…}` turned into `(e) => {…}`, or a local function's name. */
function saysItOnThePage(src: string, handler: string): boolean {
  let text = handler.trim();
  const named = /^([A-Za-z_$][\w$]*)$/.exec(text);
  if (named) {
    const def = new RegExp(`(?:const|let)\\s+${named[1].replace('$', '\\$')}\\s*=\\s*`).exec(src);
    if (!def) return false;
    text = src.slice(def.index + def[0].length, def.index + def[0].length + 400);
  }
  // A line kept for the refusals the global toast already leaves to the page
  // (`globalErrorToastMessage`): a full library, a refused sync.
  if (/\bis(?:DocumentCap|Sync)Refusal\(/.test(text)) return false;
  if (/\bset[A-Z]\w*\(\s*['"`]/.test(text)) return true;
  const param = /^(?:async\s*)?\(\s*([A-Za-z_$][\w$]*)/.exec(text) ?? /^([A-Za-z_$][\w$]*)\s*=>/.exec(text);
  if (!param) return false;
  const body = text.slice(param.index + param[0].length);
  const handedOn = new RegExp(`\\b([A-Za-z_$][\\w$]*)\\s*\\(\\s*\\(?\\s*${param[1].replace('$', '\\$')}\\b`, 'g');
  return [...body.matchAll(handedOn)].some((m) => !/^is[A-Z]/.test(m[1]));
}

/** Every place in `src` where a line on the page sits beside the global toast. */
function linesTheToastRepeats(src: string, hooks: Map<string, MetaWhen>): number[] {
  // Which mutation each name holds, and whether its `meta` is set for this caller.
  const standsAside = new Map<string, boolean>();
  for (const m of src.matchAll(/\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(use\w+)\(/g)) {
    const open = m.index! + m[0].length - 1;
    const args = src.slice(open + 1, closing(src, open) - 1);
    const when = m[2] === 'useMutation' ? metaWhen(args) : hooks.get(m[2]);
    if (when) standsAside.set(m[1], when === 'always' || (when === 'option' && args.trim() !== ''));
  }
  const repeats = (names: string[]) => names.some((n) => standsAside.get(n) === false);
  const found: number[] = [];
  // A per-call `onError`.
  for (const m of src.matchAll(/\b([A-Za-z_$][\w$]*)\s*\.(mutate|mutateAsync)\(/g)) {
    const open = m.index! + m[0].length - 1;
    const args = src.slice(open, closing(src, open));
    if (repeats([m[1]]) && onErrorValues(args).some((v) => saysItOnThePage(src, v))) found.push(lineOf(src, m.index!));
  }
  // The `catch` of a `try` that awaits a `mutateAsync`.
  for (const m of src.matchAll(/\btry\s*\{/g)) {
    const open = m.index! + m[0].length - 1;
    const end = closing(src, open);
    const names = [...src.slice(open, end).matchAll(/\b([A-Za-z_$][\w$]*)\s*\.mutateAsync\(/g)].map((n) => n[1]);
    const handler = /^\s*catch\s*(?:\(\s*([A-Za-z_$][\w$]*)[^)]*\))?\s*\{/.exec(src.slice(end));
    if (!names.length || !handler) continue;
    const catchOpen = end + handler[0].length - 1;
    const body = src.slice(catchOpen, closing(src, catchOpen));
    if (repeats(names) && saysItOnThePage(src, `(${handler[1] ?? ''}) => ${body}`)) found.push(lineOf(src, m.index!));
  }
  // `.mutateAsync(...).then(...).catch(...)`.
  for (const m of src.matchAll(/\b([A-Za-z_$][\w$]*)\s*\.mutateAsync\(/g)) {
    let i = closing(src, m.index! + m[0].length - 1);
    for (let chained = /^\s*\.(then|catch|finally)\(/.exec(src.slice(i)); chained; chained = /^\s*\.(then|catch|finally)\(/.exec(src.slice(i))) {
      const open = i + chained[0].length - 1;
      const close = closing(src, open);
      if (chained[1] === 'catch' && repeats([m[1]]) && saysItOnThePage(src, src.slice(open + 1, close - 1))) {
        found.push(lineOf(src, m.index!));
      }
      i = close;
    }
  }
  return found;
}

/**
 * Lines the global toast still repeats, known and not yet changed. The guard
 * holds every other module to the rule, and fails when one of these is fixed,
 * so the list cannot outlive what it names.
 */
const NOT_YET: Record<string, string> = {
  // The dialog says a failure, and the global toast says it too. Closing the
  // dialog mid-request unmounts it, and its line with it, so the toast is the
  // only word then. What it should say then is the owner's call (T-3.4.1.18).
  'src/components/echo/QuickShare.tsx': 'waits on the owner’s ruling',
  // The first-run step says a failed start under its button, and the global
  // toast says it too; the same page does it for saving the channels and for the
  // approval, through a prop and `isError`, which this guard does not follow.
  // Found by this guard after T-3.4.1.18 was filed, and left for its own task.
  'src/pages/WelcomePage.tsx': 'found by this guard, not yet in a task',
};

describe('the second guard', () => {
  const sources = import.meta.glob(['../../**/*.{ts,tsx}', '!**/__tests__/**', '!**/*.test.{ts,tsx}'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;
  const hooks = mutationHooks(sources);

  it('knows how each hook sets `meta`', () => {
    expect(hooks.get('useDeleteTag')).toBe('always');
    expect(hooks.get('useCreateShare')).toBe('option');
    expect(hooks.get('useAskLibraryQA')).toBe('option');
    expect(hooks.get('useCreateShelf')).toBe('never');
  });

  it('finds no line on a page that the global toast repeats, but those known and not yet changed', () => {
    const offenders = Object.entries(sources)
      .map(([file, src]) => [file.replace('../../', 'src/'), linesTheToastRepeats(src, hooks)] as const)
      .filter(([, lines]) => lines.length > 0)
      .map(([file]) => file);
    expect(offenders.sort()).toEqual(Object.keys(NOT_YET).sort());
  });

  const HOOKS = new Map<string, MetaWhen>([
    ['useBare', 'never'],
    ['useQuiet', 'always'],
    ['useEither', 'option'],
  ]);

  it.each([
    ["const x = useBare();\nx.mutate(p, { onError: (err) => setError(apiErrorMessage(err, 'No.')) });"],
    ["const x = useBare();\nx.mutate(p, { onError: () => setError('No.') });"],
    ["const x = useBare();\nconst fail = (err: unknown) =>\n  setError(detailFromErrorBody((err as E).response?.data) ?? 'No.');\nx.mutate(p, { onError: fail });"],
    ["const x = useEither();\nasync function go() {\n  try {\n    await x.mutateAsync(p);\n  } catch (err) {\n    updateTurn(id, { status: 'error', error: requestErrorLine(err) });\n  }\n}"],
    ["const x = useBare();\nx.mutateAsync(p).then(() => go()).catch((e) => setError(inlineErrorMessage(e, 'No.')));"],
    ["const x = useBare();\nx\n  .mutateAsync(p)\n  .then(() => go())\n  .catch((e) => setError(inlineErrorMessage(e, 'No.')));"],
    ["const m = useMutation({ mutationFn: f });\nm.mutate(p, { onError: (e) => setError(apiErrorMessage(e, 'No.')) });"],
  ])('catches %s', (src) => {
    expect(linesTheToastRepeats(src, HOOKS)).toHaveLength(1);
  });

  it.each([
    ["const x = useQuiet();\nx.mutate(p, { onError: (err) => setError(inlineErrorMessage(err, 'No.')) });"],
    ["const x = useEither({ inlineErrors: true });\ntry {\n  await x.mutateAsync(p);\n} catch (err) {\n  updateTurn(id, { error: requestErrorLine(err) });\n}"],
    ["const x = useBare();\ntry {\n  await x.mutateAsync(p);\n} catch (err) {\n  if (mounted.current && !isSessionEnded(err)) await again();\n}"],
    ["const x = useBare();\ntry {\n  await x.mutateAsync(p);\n} catch {\n  return; // the global toast said it\n}"],
    ["const x = useBare();\nx.mutate(p, { onSuccess: () => setConfirming(false) });"],
    ["const x = useBare();\nx.mutateAsync(p).then(() => go(), () => undefined);"],
    ["const x = useBare();\ntry {\n  await x.mutateAsync(p);\n} catch (err) {\n  if (isDocumentCapRefusal(err)) setError(apiErrorMessage(err, 'Full.'));\n}"],
    ["const m = useMutation({ mutationFn: f, meta: ERRORS_SHOWN_HERE });\nm.mutate(p, { onError: (e) => setError(apiErrorMessage(e, 'No.')) });"],
    ["onSubmit={(v) => update.mutateAsync(v)}"],
  ])('leaves alone %s', (src) => {
    expect(linesTheToastRepeats(src, HOOKS)).toEqual([]);
  });
});
