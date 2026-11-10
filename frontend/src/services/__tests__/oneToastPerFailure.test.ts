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
 * again. A third holds the other side: a hook whose `meta` leaves the failure to
 * its caller's line gets no caller without one, or the failure is said nowhere.
 * Since T-3.4.1.22 both also follow a line through a dialog's or picker's
 * callback prop and through a mutation's `isError`.
 *
 * A fourth guard holds the same two sides for queries (T-3.4.1.26): a reader
 * that says a load's failure on the page stands aside from the query toast, and
 * a reader that stands aside says it.
 *
 * A fifth, at the end, holds polls (T-3.4.1.27): the query client says a run of
 * a poll's failures once, so every `refetchInterval` is listed beside the test
 * that checks it, and nothing polls by a timer the client cannot see.
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
// ignores it leaves the global toast to speak, as it should. A mutation passed in
// a callback prop, and a line read from a mutation's state, are read below
// (T-3.4.1.22).
//
// Mutation checks, run on 2026-11-09: taking `meta` off `useDeleteTag`,
// `useDeleteShelf`, `useDeleteTemplate` or `useCompleteConnector`, or dropping
// `{ inlineErrors: true }` from the Echo bubble's `useAskLibraryQA`, each fails
// "finds no line on a page that the global toast repeats", naming that file.
// An option hook stands aside only when the caller sets that option to `true`:
// the bubble passing `{ inlineErrors: false }` fails it too.

/** How a mutation sets `meta`: always, only when a caller passes `option: true`,
 * or never; and whether its own `onError` toasts the failure. */
interface HookMeta {
  when: 'always' | 'option' | 'never';
  option?: string;
  toasts: boolean;
}

/** `options` is the object handed to `useMutation`; `src` its module, for the
 * local helpers an `onError` may call. */
function hookMeta(src: string, options: string): HookMeta {
  const toasts = onErrorValues(options).some((v) => toastsInOnError(src, v));
  const meta = /\bmeta\s*:\s*([^,\n}]+)/.exec(options);
  if (!meta) return { when: 'never', toasts };
  if (!meta[1].includes('?')) return { when: 'always', toasts };
  return { when: 'option', option: /^\s*([A-Za-z_$][\w$]*)\s*\?/.exec(meta[1])?.[1], toasts };
}

function mutationHooks(sources: Record<string, string>): Map<string, HookMeta> {
  const hooks = new Map<string, HookMeta>();
  for (const src of Object.values(sources)) {
    const starts = [...src.matchAll(/export function (use\w+)\s*\(/g)];
    starts.forEach((m, k) => {
      const body = src.slice(m.index!, starts[k + 1]?.index ?? src.length);
      const call = /\buseMutation\(\s*\{/.exec(body);
      if (!call) return;
      const open = call.index + call[0].length - 1;
      hooks.set(m[1], hookMeta(src, body.slice(open, closing(body, open))));
    });
  }
  return hooks;
}

/** What each name in `src` holds: whether the global toast stands aside for
 * this caller, and whether the hook toasts the failure itself. An option hook
 * stands aside only when this caller sets its option to `true`. */
function mutationsIn(src: string, hooks: Map<string, HookMeta>): Map<string, { standsAside: boolean; toasts: boolean }> {
  const held = new Map<string, { standsAside: boolean; toasts: boolean }>();
  for (const m of src.matchAll(/\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(use\w+)\(/g)) {
    const open = m.index! + m[0].length - 1;
    const args = src.slice(open + 1, closing(src, open) - 1);
    const meta = m[2] === 'useMutation' ? hookMeta(src, args) : hooks.get(m[2]);
    if (!meta) continue;
    const optionOn = !!meta.option && new RegExp(`\\b${meta.option.replace('$', '\\$')}\\s*:\\s*true\\b`).test(args);
    held.set(m[1], { standsAside: meta.when === 'always' || (meta.when === 'option' && optionOn), toasts: meta.toasts });
  }
  return held;
}

const CHAINED = /^\s*\.(then|catch|finally)\(/;

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

// ---------------------------------------------------------------------------
// A line reached through a prop, or read from the mutation's state
// ---------------------------------------------------------------------------
//
// Two more ways a page says a failed mutation where the reader acted, which the
// handlers above do not show (T-3.4.1.22):
// - through a prop: a dialog or picker awaits a callback in a `try` whose
//   `catch` says the failure (`ShelfFormModal`'s `onSubmit`, `LabelPicker`'s
//   `onToggle`), and its caller passes a mutation in that callback;
// - from the mutation's state: the page reads `x.isError` or `x.error` and
//   builds a line from it (the channel page's subscribe and sync).
// Both count as a line, for the second guard and the third alike.
//
// Mutation checks, run on 2026-11-09: dropping the prop reading from the second
// guard fails its four prop cases below, and dropping the state reading its two
// state cases and the module scan. Taking `meta` off `useApproveJob`,
// `useCreateShelf`, `useSubscribeChannel`, `useSetChannelWeight` or `useApplyTag`,
// or `{ inlineErrors: true }` off the wizard's start or saves, the templates
// page's rename or the picker's remove, fails "finds no line on a page that the
// global toast repeats". Setting `meta` for every caller of
// `useUpdateOnboarding`, `useUpdateTemplate`, `useRemoveJobFromShelf` or
// `useCreateJob` fails the third guard's "finds no mutation whose failure is
// said nowhere".

/** Whether `index` starts the argument of an `is…Refusal(` check, a line kept for
 * the refusals the global toast already leaves to the page. */
function inRefusalCheck(src: string, index: number): boolean {
  return /\bis(?:DocumentCap|Sync)Refusal\(\s*$/.test(src.slice(Math.max(0, index - 40), index));
}

/** Each name whose failure `src` reads from its state, with where it first does. */
function shownFromState(src: string): Map<string, number> {
  const shown = new Map<string, number>();
  for (const m of src.matchAll(/\b([A-Za-z_$][\w$]*)\s*\.\s*(?:isError|error)\b/g)) {
    if (!inRefusalCheck(src, m.index!) && !shown.has(m[1])) shown.set(m[1], m.index!);
  }
  return shown;
}

/** Function components in `src`: name, parameter text and body. */
function componentsIn(src: string): Array<{ name: string; params: string; body: [number, number] }> {
  const found: Array<{ name: string; params: string; body: [number, number] }> = [];
  for (const m of src.matchAll(/\bfunction\s+([A-Z][\w$]*)\s*\(/g)) {
    const open = m.index! + m[0].length - 1;
    const paramsEnd = closing(src, open);
    const bodyOpen = src.indexOf('{', paramsEnd);
    if (bodyOpen === -1) continue;
    found.push({ name: m[1], params: src.slice(open, paramsEnd), body: [bodyOpen, closing(src, bodyOpen)] });
  }
  return found;
}

/** For each component, the callback props whose failure it says on the page: an
 * `await onSubmit(…)` in a `try` whose `catch` says it, or an
 * `onContinue(…).catch(…)` that does. */
function lineProps(sources: Record<string, string>): Map<string, Set<string>> {
  const props = new Map<string, Set<string>>();
  for (const src of Object.values(sources)) {
    for (const comp of componentsIn(src)) {
      const isParam = (name: string) => new RegExp(`\\b${name.replace('$', '\\$')}\\b`).test(comp.params);
      const names = new Set<string>();
      const [from, to] = comp.body;
      for (const m of src.slice(from, to).matchAll(/\btry\s*\{/g)) {
        const open = from + m.index! + m[0].length - 1;
        const end = closing(src, open);
        const handler = /^\s*catch\s*(?:\(\s*([A-Za-z_$][\w$]*)[^)]*\))?\s*\{/.exec(src.slice(end));
        if (!handler) continue;
        const catchOpen = end + handler[0].length - 1;
        if (!saysItOnThePage(src, `(${handler[1] ?? ''}) => ${src.slice(catchOpen, closing(src, catchOpen))}`)) continue;
        for (const call of src.slice(open, end).matchAll(/\bawait\s+([A-Za-z_$][\w$]*)\s*\(/g)) {
          if (isParam(call[1])) names.add(call[1]);
        }
      }
      for (const call of src.slice(from, to).matchAll(/(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(/g)) {
        if (!isParam(call[1])) continue;
        let i = closing(src, from + call.index! + call[0].length - 1);
        for (let chained = CHAINED.exec(src.slice(i)); chained; chained = CHAINED.exec(src.slice(i))) {
          const open = i + chained[0].length - 1;
          const close = closing(src, open);
          if (chained[1] === 'catch' && saysItOnThePage(src, src.slice(open + 1, close - 1))) names.add(call[1]);
          i = close;
        }
      }
      if (names.size) props.set(comp.name, new Set([...(props.get(comp.name) ?? []), ...names]));
    }
  }
  return props;
}

/** The statement that defines a local function `name`, if `src` has one. */
function localFunction(src: string, name: string): [number, number] | null {
  const def = new RegExp(`\\b(?:const|let)\\s+${name.replace('$', '\\$')}\\s*=|\\bfunction\\s+${name.replace('$', '\\$')}\\s*\\(`).exec(src);
  if (!def) return null;
  let i = def.index + def[0].length;
  if (def[0].endsWith('(')) {
    const bodyOpen = src.indexOf('{', closing(src, i - 1));
    return bodyOpen === -1 ? null : [def.index, closing(src, bodyOpen)];
  }
  while (i < src.length && src[i] !== ';') i = '({['.includes(src[i]) ? closing(src, i) : i + 1;
  return [def.index, i];
}

/** The parts of `src` that a component's line answers for: the value of each of
 * its line props where `src` renders it, and the local function passed as one. */
function lineSpans(src: string, props: Map<string, Set<string>>): Array<[number, number]> {
  const spans: Array<[number, number]> = [];
  for (const [comp, names] of props) {
    for (const m of src.matchAll(new RegExp(`<${comp}\\b`, 'g'))) {
      let end = m.index! + m[0].length;
      while (end < src.length && src[end] !== '>') end = src[end] === '{' ? closing(src, end) : end + 1;
      for (const name of names) {
        const attr = new RegExp(`\\b${name}\\s*=\\s*\\{`, 'g');
        attr.lastIndex = m.index!;
        const a = attr.exec(src);
        if (!a || a.index > end) continue;
        const open = a.index + a[0].length - 1;
        const close = closing(src, open);
        spans.push([open, close]);
        const local = /^\{\s*([A-Za-z_$][\w$]*)\s*\}$/.exec(src.slice(open, close));
        const body = local && localFunction(src, local[1]);
        if (body) spans.push(body);
      }
    }
  }
  return spans;
}

/** The mutations `text` calls or hands on: `x.mutateAsync`, and both sides of
 * `(on ? add : remove).mutateAsync`. */
function mutationsCalledIn(text: string): string[] {
  const names = [...text.matchAll(/\b([A-Za-z_$][\w$]*)\s*\.\s*(?:mutate|mutateAsync)\b/g)].map((m) => m[1]);
  for (const m of text.matchAll(/\(\s*[^()?]+\?\s*([A-Za-z_$][\w$]*)\s*:\s*([A-Za-z_$][\w$]*)\s*\)\s*\.\s*(?:mutate|mutateAsync)\b/g)) {
    names.push(m[1], m[2]);
  }
  return names;
}

/** Every place in `src` where a line on the page sits beside the global toast. */
function linesTheToastRepeats(src: string, hooks: Map<string, HookMeta>, props = new Map<string, Set<string>>()): number[] {
  // Which mutation each name holds, and whether its `meta` is set for this caller.
  const held = mutationsIn(src, hooks);
  const repeats = (names: string[]) => names.some((n) => held.get(n)?.standsAside === false);
  const found: number[] = [];
  // A line read from the mutation's state.
  for (const [name, index] of shownFromState(src)) if (repeats([name])) found.push(lineOf(src, index));
  // A line in a component the mutation reaches through a prop.
  for (const [open, close] of lineSpans(src, props)) {
    if (repeats(mutationsCalledIn(src.slice(open, close)))) found.push(lineOf(src, open));
  }
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

// ---------------------------------------------------------------------------
// The third guard: a failure the toast leaves to the page is said there
// ---------------------------------------------------------------------------
//
// The other side of the second guard. A hook that sets `meta` and says nothing
// in its own `onError` (the tags manager's, the delete-shelf modal's, a bubble
// ask with `inlineErrors: true`) leaves every failure to its caller's line. A
// caller with no line would say it nowhere: no toast, because of `meta`, and no
// line. So every `mutate` / `mutateAsync` on such a mutation needs a handler
// that says the failure on the page, read as the second guard reads one.
//
// Mutation check, run on 2026-11-09: dropping the per-call `onError` from the
// tags manager's delete, or the `catch` from the callback page's `mutateAsync`,
// fails "finds no mutation whose failure is said nowhere", naming that file.

/** Every call in `src` whose failure is said nowhere: the global toast stands
 * aside for it, its hook says nothing, and the call has no line of its own. */
function failuresSaidNowhere(src: string, hooks: Map<string, HookMeta>, props = new Map<string, Set<string>>()): number[] {
  const held = mutationsIn(src, hooks);
  // A line read from the mutation's state, or in a component it reaches through
  // a prop, says the failure as well as a handler does.
  const fromState = shownFromState(src);
  const spans = lineSpans(src, props);
  const silent = (name: string) => {
    const h = held.get(name);
    return !!h && h.standsAside && !h.toasts && !fromState.has(name);
  };
  // The `try` blocks whose `catch` says the failure on the page.
  const caught: Array<[number, number]> = [];
  for (const m of src.matchAll(/\btry\s*\{/g)) {
    const open = m.index! + m[0].length - 1;
    const end = closing(src, open);
    const handler = /^\s*catch\s*(?:\(\s*([A-Za-z_$][\w$]*)[^)]*\))?\s*\{/.exec(src.slice(end));
    if (!handler) continue;
    const catchOpen = end + handler[0].length - 1;
    const body = src.slice(catchOpen, closing(src, catchOpen));
    if (saysItOnThePage(src, `(${handler[1] ?? ''}) => ${body}`)) caught.push([open, end]);
  }
  const found: number[] = [];
  for (const m of src.matchAll(/\b([A-Za-z_$][\w$]*)\s*\.(mutate|mutateAsync)\(/g)) {
    if (!silent(m[1])) continue;
    if (spans.some(([a, b]) => m.index! > a && m.index! < b)) continue;
    const open = m.index! + m[0].length - 1;
    const close = closing(src, open);
    if (onErrorValues(src.slice(open, close)).some((v) => saysItOnThePage(src, v))) continue;
    if (m[2] === 'mutateAsync') {
      if (caught.some(([a, b]) => m.index! > a && m.index! < b)) continue;
      let said = false;
      let i = close;
      for (let chained = CHAINED.exec(src.slice(i)); chained; chained = CHAINED.exec(src.slice(i))) {
        const from = i + chained[0].length - 1;
        const to = closing(src, from);
        if (chained[1] === 'catch' && saysItOnThePage(src, src.slice(from + 1, to - 1))) said = true;
        i = to;
      }
      if (said) continue;
    }
    found.push(lineOf(src, m.index!));
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
  // T-3.4.1.24 took off the seven files the state reading found (T-3.4.1.22):
  // DraftEditor, VideoFramesPanel, PasteUrlsForm, NotesPanel,
  // PinQuestionButton, NotesPage and SavedSearchesPage. Mutation check, run on
  // 2026-11-09: taking `meta` off `useDraftFeedback` fails "knows how each hook
  // sets `meta`" and this guard's "finds no line", naming DraftEditor; `meta`
  // on `useDeleteNote` fails the third guard's "finds no mutation whose
  // failure is said nowhere", since neither caller of a note's delete has a line.
};

/** Stand-ins for the hooks the guards read: one with no `meta`, one that sets
 * it and leaves the failure to its caller, one that sets it and toasts, and one
 * whose `meta` waits on an option. */
const HOOKS = new Map<string, HookMeta>([
  ['useBare', { when: 'never', toasts: false }],
  ['useQuiet', { when: 'always', toasts: false }],
  ['useLoud', { when: 'always', toasts: true }],
  ['useEither', { when: 'option', option: 'inlineErrors', toasts: false }],
]);

/** Stand-ins for components that say a callback's failure on the page: a form's
 * `onSubmit` and a picker's `onToggle`. */
const PROPS = new Map<string, Set<string>>([
  ['Form', new Set(['onSubmit'])],
  ['Picker', new Set(['onToggle'])],
]);

describe('the second guard', () => {
  const sources = import.meta.glob(['../../**/*.{ts,tsx}', '!**/__tests__/**', '!**/*.test.{ts,tsx}'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;
  const hooks = mutationHooks(sources);
  const props = lineProps(sources);

  it('knows how each hook sets `meta`, and whether it toasts', () => {
    expect(hooks.get('useDeleteTag')).toEqual({ when: 'always', toasts: false });
    expect(hooks.get('useCreateShare')).toEqual({ when: 'option', option: 'toastErrors', toasts: true });
    expect(hooks.get('useAskLibraryQA')).toEqual({ when: 'option', option: 'inlineErrors', toasts: false });
    expect(hooks.get('useCreateDraft')).toEqual({ when: 'always', toasts: true });
    expect(hooks.get('useCancelJob')).toEqual({ when: 'never', toasts: false });
    // T-3.4.1.22: a hook every caller answers on the page, and one whose callers differ.
    expect(hooks.get('useApproveJob')).toEqual({ when: 'always', toasts: false });
    expect(hooks.get('useCreateJob')).toEqual({ when: 'option', option: 'inlineErrors', toasts: false });
    // T-3.4.1.24: every caller of these shows a line; a note's delete shows none.
    for (const name of [
      'useDraftFeedback',
      'useExtractFrames',
      'usePasteUrls',
      'useCreateNote',
      'useUpdateNote',
      'useCreateSavedSearch',
      'useUpdateSavedSearch',
      'useRunSavedSearchNow',
      'useDeleteSavedSearch',
    ]) {
      expect(hooks.get(name), name).toEqual({ when: 'always', toasts: false });
    }
    expect(hooks.get('useDeleteNote')).toEqual({ when: 'never', toasts: false });
  });

  it('finds no line on a page that the global toast repeats, but those known and not yet changed', () => {
    const offenders = Object.entries(sources)
      .map(([file, src]) => [file.replace('../../', 'src/'), linesTheToastRepeats(src, hooks, props)] as const)
      .filter(([, lines]) => lines.length > 0)
      .map(([file]) => file);
    expect(offenders.sort()).toEqual(Object.keys(NOT_YET).sort());
  });

  it('reads the callbacks a dialog or picker says the failure of (T-3.4.1.22)', () => {
    expect(props.get('ShelfFormModal')).toEqual(new Set(['onSubmit']));
    expect(props.get('SaveTemplateModal')).toEqual(new Set(['onSubmit']));
    expect(props.get('LabelPicker')).toEqual(new Set(['onToggle', 'onCreate']));
    expect(props.get('VideoApprovalSection')).toEqual(new Set(['onApprove']));
    expect(props.get('ChannelsStep')).toEqual(new Set(['onContinue']));
    expect(props.get('FirstRunStep')).toEqual(new Set(['onStarted']));
  });

  it.each([
    [
      "function Form({ onSubmit, onClose }: P) {\n  const go = async () => {\n    try {\n      await onSubmit(v);\n      onClose();\n    } catch (err) {\n      setError(inlineErrorMessage(err, 'No.'));\n    }\n  };\n}",
      'Form',
      ['onSubmit'],
    ],
    [
      "function Step({ onContinue }: P) {\n  return <Button onClick={() => onContinue(c).catch((err) => setError(inlineErrorMessage(err, 'No.')))} />;\n}",
      'Step',
      ['onContinue'],
    ],
  ])('reads a line prop in %s', (src, comp, names) => {
    expect(lineProps({ src })).toEqual(new Map([[comp, new Set(names)]]));
  });

  it.each([
    ['function Quiet({ onDone }: P) {\n  const go = async () => {\n    try {\n      await onDone();\n    } catch {\n      // the global toast said it\n    }\n  };\n}'],
    ["function Local() {\n  const go = async () => {\n    try {\n      await save();\n    } catch (err) {\n      setError(inlineErrorMessage(err, 'No.'));\n    }\n  };\n}"],
  ])('reads no line prop in %s', (src) => {
    expect(lineProps({ src })).toEqual(new Map());
  });

  it.each([
    // A line read from the mutation's state.
    ["const x = useBare();\nconst line = x.isError ? apiErrorMessage(x.error, 'No.') : null;"],
    ['const x = useBare();\nreturn <>{x.isError && <p role="alert">No.</p>}</>;'],
    // A line in a component the mutation reaches through a prop.
    ['const x = useBare();\nreturn <Form onSubmit={(v) => x.mutateAsync(v)} />;'],
    ['const x = useBare();\nconst save = async (v: V) => {\n  await x.mutateAsync(v);\n  go();\n};\nreturn <Form title="New" onSubmit={save} />;'],
    ['const add = useQuiet();\nconst remove = useBare();\nreturn <Picker onToggle={(l, on) => (on ? add : remove).mutateAsync(l)} />;'],
    ['const x = useBare();\nreturn <VideoList onApprove={x.mutateAsync} />;'],
  ])('catches %s', (src) => {
    expect(linesTheToastRepeats(src, HOOKS, new Map([...PROPS, ['VideoList', new Set(['onApprove'])]]))).toHaveLength(1);
  });

  it.each([
    ["const x = useQuiet();\nconst line = x.isError ? inlineErrorMessage(x.error, 'No.') : null;"],
    ['const x = useBare();\nconst full = isDocumentCapRefusal(x.error);'],
    ['const x = useQuiet();\nreturn <Form onSubmit={(v) => x.mutateAsync(v)} />;'],
    ['const x = useEither({ inlineErrors: true });\nreturn <Picker onToggle={(l) => x.mutateAsync(l)} />;'],
    ['const x = useBare();\nreturn <Form onClose={() => x.mutate(p)} />;'],
    ['const x = useBare();\nreturn <Other onSubmit={(v) => x.mutateAsync(v)} />;'],
  ])('leaves alone %s', (src) => {
    expect(linesTheToastRepeats(src, HOOKS, PROPS)).toEqual([]);
  });

  it.each([
    ["const x = useBare();\nx.mutate(p, { onError: (err) => setError(apiErrorMessage(err, 'No.')) });"],
    ["const x = useBare();\nx.mutate(p, { onError: () => setError('No.') });"],
    ["const x = useBare();\nconst fail = (err: unknown) =>\n  setError(detailFromErrorBody((err as E).response?.data) ?? 'No.');\nx.mutate(p, { onError: fail });"],
    ["const x = useEither();\nasync function go() {\n  try {\n    await x.mutateAsync(p);\n  } catch (err) {\n    updateTurn(id, { status: 'error', error: requestErrorLine(err) });\n  }\n}"],
    ["const x = useBare();\nx.mutateAsync(p).then(() => go()).catch((e) => setError(inlineErrorMessage(e, 'No.')));"],
    ["const x = useBare();\nx\n  .mutateAsync(p)\n  .then(() => go())\n  .catch((e) => setError(inlineErrorMessage(e, 'No.')));"],
    ["const m = useMutation({ mutationFn: f });\nm.mutate(p, { onError: (e) => setError(apiErrorMessage(e, 'No.')) });"],
    // An option hook stands aside only when its option is set to true.
    ["const x = useEither({ inlineErrors: false });\nx.mutate(p, { onError: (err) => setError(inlineErrorMessage(err, 'No.')) });"],
    ["const x = useEither({ other: true });\nx.mutate(p, { onError: (err) => setError(inlineErrorMessage(err, 'No.')) });"],
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

describe('the third guard', () => {
  const sources = import.meta.glob(['../../**/*.{ts,tsx}', '!**/__tests__/**', '!**/*.test.{ts,tsx}'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;
  const hooks = mutationHooks(sources);
  const props = lineProps(sources);

  it('reads the hooks that leave every failure to their callers', () => {
    const silent = [...hooks].filter(([, h]) => h.when === 'always' && !h.toasts).map(([name]) => name);
    expect(silent).toEqual(
      expect.arrayContaining(['useUpdateTag', 'useDeleteTag', 'useDeleteShelf', 'useDeleteTemplate', 'useCompleteConnector']),
    );
  });

  it('finds no mutation whose failure is said nowhere', () => {
    const offenders = Object.entries(sources)
      .map(([file, src]) => [file.replace('../../', 'src/'), failuresSaidNowhere(src, hooks, props)] as const)
      .filter(([, lines]) => lines.length > 0)
      .map(([file, lines]) => `${file}:${lines.join(',')}`);
    expect(offenders).toEqual([]);
  });

  it.each([
    ['const x = useQuiet();\nreturn <Other onSubmit={(v) => x.mutateAsync(v)} />;'],
    ['const x = useQuiet();\nreturn <Form onClose={() => x.mutate(p)} />;'],
    ['const x = useQuiet();\nconst save = (v: V) => x.mutateAsync(v);\nreturn <Other onSubmit={save} />;'],
  ])('catches a call no line answers for: %s', (src) => {
    expect(failuresSaidNowhere(src, HOOKS, PROPS)).toHaveLength(1);
  });

  it.each([
    ['const x = useQuiet();\nreturn <Form onSubmit={(v) => x.mutateAsync(v)} />;'],
    ['const x = useQuiet();\nconst save = (v: V) => x.mutateAsync(v);\nreturn <Form onSubmit={save} />;'],
    ['const x = useQuiet();\nconst save = async (v: V) => {\n  const made = await x.mutateAsync(v);\n  go(made);\n};\nreturn <Form onSubmit={save} />;'],
    ["const x = useQuiet();\nx.mutate(p);\nconst line = x.isError ? inlineErrorMessage(x.error, 'No.') : null;"],
  ])('leaves alone a call a line answers for: %s', (src) => {
    expect(failuresSaidNowhere(src, HOOKS, PROPS)).toEqual([]);
  });

  it.each([
    ['const del = useQuiet();\ndel.mutate({ id });'],
    ['const del = useQuiet();\ndel.mutate({ id }, { onSuccess: () => close() });'],
    ['const del = useQuiet();\nasync function go() {\n  await del.mutateAsync({ id });\n}'],
    ['const del = useQuiet();\ntry {\n  await del.mutateAsync({ id });\n} catch (err) {\n  if (isSessionEnded(err)) return;\n}'],
    ['const del = useQuiet();\ndel.mutateAsync({ id }).then(() => go(), () => undefined);'],
    ['const x = useEither({ inlineErrors: true });\nx.mutate(p);'],
    ['const m = useMutation({ mutationFn: f, meta: ERRORS_SHOWN_HERE });\nm.mutate(p);'],
  ])('catches %s', (src) => {
    expect(failuresSaidNowhere(src, HOOKS)).toHaveLength(1);
  });

  it.each([
    ["const del = useQuiet();\ndel.mutate({ id }, { onError: (err) => setError(inlineErrorMessage(err, 'No.')) });"],
    ["const del = useQuiet();\ntry {\n  await del.mutateAsync({ id });\n} catch (err) {\n  setError(inlineErrorMessage(err, 'No.'));\n}"],
    ["const del = useQuiet();\ndel\n  .mutateAsync({ id })\n  .then(() => go())\n  .catch((e) => setError(inlineErrorMessage(e, 'No.')));"],
    ["const del = useQuiet();\ntry {\n  await del.mutateAsync({ id });\n} catch {\n  setError('No.');\n}"],
    ['const x = useLoud();\nx.mutate(p);'],
    ['const x = useBare();\nx.mutate(p);'],
    ['const x = useEither();\nx.mutate(p);'],
    ['const x = useEither({ inlineErrors: false });\nx.mutate(p);'],
    ["const m = useMutation({ mutationFn: f, onError: (e) => toastMutationError(e, 'No.'), meta: ERRORS_SHOWN_HERE });\nm.mutate(p);"],
  ])('leaves alone %s', (src) => {
    expect(failuresSaidNowhere(src, HOOKS)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// The fourth guard: a query's failure line stands alone (T-3.4.1.26)
// ---------------------------------------------------------------------------
//
// A failed query goes through the `QueryCache`, which toasts it once its retry
// has failed too, unless a reader of the query mounted now sets `meta`:
// `ERRORS_SHOWN_HERE`, or `LOAD_ERRORS_SHOWN_HERE` for a line shown only in
// place of a first load (`queryFailureShownOnPage`). Each reader (a `useQuery`
// call, or a call of a hook that wraps one) carries its own `meta`, so the rule
// is checked per reader, with the same two sides as for mutations:
// - a reader that builds a line from the query's failure (`q.isError`,
//   `q.error` or `q.status === 'error'`, destructured or not, or the query
//   handed to a component prop that reads them) stands aside, or the toast says
//   the failure again;
// - a reader that stands aside builds such a line, or the failure is said
//   nowhere wherever it is mounted alone. A read that only hides the component
//   or leaves the page (`if (q.isError) return null`, `return <Navigate …/>`)
//   is no line, and neither is a call that keeps no result (`useX().data`).
// A hook whose readers differ takes `inlineErrors` (`queryErrorsMeta`); a
// caller stands aside when it passes that option as anything but `false`. A
// reader that stands aside only at times, by a condition (`tab === 'videos'`)
// or only in place of a first load (`'load'`, `LOAD_ERRORS_SHOWN_HERE`), is
// one this guard cannot judge: whether its line shows exactly when it stands
// aside is for a page test to check, both ways round. So every file with such
// a reader is listed in `CONDITIONAL_READERS` with the test that does, and the
// guard fails on a file missing from the list (a new condition nothing checks)
// or listed with none.
//
// Mutation checks, run on 2026-11-10: taking `meta` off `useNotesList`,
// `useSavedSearches`, `useDraftStatus` or the system page's polls, or
// `{ inlineErrors: true }` off the shelves page's `useShelves`, fails "finds no
// query line the toast repeats", naming that file; setting `meta` for every
// caller of `useShelves`, `useOnboarding` or `useEchoStatus` fails it too,
// naming the sidebar, the gate or the Echo panel, where nothing says the
// failure; dropping the prop reading fails "reads the query a section is
// handed" and names the system page; taking the library page or the report
// peek out of `CONDITIONAL_READERS` fails "names the page test", as do a
// listed test that does not exist, `LOAD_ERRORS_SHOWN_HERE` read as standing
// aside always, and `inlineErrors: true` counted as a condition.

interface QueryHookMeta {
  when: 'always' | 'option' | 'never';
  option?: string;
  /** Set when the hook stands aside only while its query has no data
   * (`LOAD_ERRORS_SHOWN_HERE`). */
  load?: true;
}

/** Whether a `meta` written as `text` stands aside only at times: in place of
 * a first load, or by a condition worked out where it is written. */
function metaAtTimes(text: string): boolean {
  const t = text.trim();
  if (t === 'LOAD_ERRORS_SHOWN_HERE') return true;
  const arg = /^queryErrorsMeta\(([\s\S]*)\)$/.exec(t)?.[1].trim();
  return arg !== undefined && arg !== 'true';
}

/** `src` with its comments blanked out, newlines kept, so a hook named in a
 * comment is not read as a call and line numbers still match. */
function withoutComments(src: string): string {
  let out = '';
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    const next = src[i + 1];
    if (ch === '/' && (next === '/' || next === '*')) {
      const end = next === '/' ? (src.indexOf('\n', i) + 1 || src.length) : src.indexOf('*/', i + 2) + 2;
      out += src.slice(i, end).replace(/[^\n]/g, ' ');
      i = end;
    } else if (ch === "'" || ch === '"' || ch === '`') {
      let j = i + 1;
      while (j < src.length && src[j] !== ch) {
        if (src[j] === '\\') j += 2;
        else if (ch === '`' && src[j] === '$' && src[j + 1] === '{') j = closing(src, j + 1);
        else j += 1;
      }
      out += src.slice(i, j + 1);
      i = j + 1;
    } else {
      out += ch;
      i += 1;
    }
  }
  return out;
}

/** The options object of the first `useQuery(…)` call in `src` at or after
 * `from` (a type argument allowed), with where the call starts. */
function findQueryCall(src: string, from = 0): { at: number; end: number; options: string } | null {
  const re = /\buseQuery\b/g;
  re.lastIndex = from;
  for (let m = re.exec(src); m; m = re.exec(src)) {
    let i = m.index + m[0].length;
    // A type argument: `useQuery<ReportBody, AxiosError<{ detail?: string }>>(`.
    if (src[i] === '<') {
      for (let depth = 0; i < src.length; i += 1) {
        if (src[i] === '<') depth += 1;
        else if (src[i] === '>' && --depth === 0) {
          i += 1;
          break;
        }
      }
    }
    const open = /^\s*\(\s*\{/.exec(src.slice(i));
    if (!open) continue;
    const paren = src.indexOf('(', i);
    const brace = i + open[0].length - 1;
    return { at: m.index, end: closing(src, paren), options: src.slice(brace, closing(src, brace)) };
  }
  return null;
}

/** How a `useQuery` options object sets `meta`: from a name passed to
 * `queryErrorsMeta` (in a hook, its option; in a component, what it works out),
 * always, or never. */
function queryMetaOf(options: string): QueryHookMeta & { text?: string } {
  const meta = /\bmeta\s*:\s*([^,\n}]+)/.exec(options);
  if (!meta) return { when: 'never' };
  const text = meta[1].trim();
  const option = /^queryErrorsMeta\(\s*([A-Za-z_$][\w$]*)\s*\)$/.exec(text);
  if (option) return { when: 'option', option: option[1], text };
  return text === 'LOAD_ERRORS_SHOWN_HERE' ? { when: 'always', load: true, text } : { when: 'always', text };
}

/** Every exported hook that wraps a `useQuery`, and how it sets `meta`. */
function queryHooks(sources: Record<string, string>): Map<string, QueryHookMeta> {
  const hooks = new Map<string, QueryHookMeta>();
  for (const src of Object.values(sources).map(withoutComments)) {
    const starts = [...src.matchAll(/export function (use\w+)\s*[<(]/g)];
    starts.forEach((m, k) => {
      const body = src.slice(m.index!, starts[k + 1]?.index ?? src.length);
      const call = findQueryCall(body);
      if (call) {
        const meta = queryMetaOf(call.options);
        delete meta.text;
        hooks.set(m[1], meta);
      }
    });
  }
  return hooks;
}

/** Whether `index` sits in the condition of an `if` whose branch only hides
 * the component or leaves the page: `return null`, `return <Navigate …/>`. */
function inSilentGuard(src: string, index: number): boolean {
  for (const m of src.matchAll(/\bif\s*\(/g)) {
    const open = m.index! + m[0].length - 1;
    if (open > index) break;
    const close = closing(src, open);
    if (index > open && index < close) return /^\s*(?:\{\s*)?return\s+(?:null\b|<Navigate\b)/.test(src.slice(close));
  }
  return false;
}

/** Each function declared in `src` (components and hooks): name, parameter
 * text and body. */
function functionsIn(src: string): Array<{ name: string; params: string; body: [number, number] }> {
  const found: Array<{ name: string; params: string; body: [number, number] }> = [];
  for (const m of src.matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)\s*(?:<[^>(]*>)?\s*\(/g)) {
    const open = m.index! + m[0].length - 1;
    const paramsEnd = closing(src, open);
    const bodyOpen = src.indexOf('{', paramsEnd);
    if (bodyOpen === -1) continue;
    found.push({ name: m[1], params: src.slice(open, paramsEnd), body: [bodyOpen, closing(src, bodyOpen)] });
  }
  return found;
}

/** The innermost function body around `index`, else the whole module. */
function scopeOf(src: string, index: number): [number, number] {
  let best: [number, number] = [0, src.length];
  for (const f of functionsIn(src)) {
    const [a, b] = f.body;
    if (index > a && index < b && b - a < best[1] - best[0]) best = [a, b];
  }
  return best;
}

const FAILURE_FIELD = String.raw`(?:isError|error|isLoadingError|isRefetchError)\b|status\s*[!=]==?\s*['"]error['"]`;

/** Where `src` reads `name`'s failure off its state between `from` and `to`,
 * other than to hide the component or leave the page. */
function failureReads(src: string, name: string, [from, to]: [number, number]): number[] {
  const re = new RegExp(String.raw`(?<![.\w$])${name.replace('$', '\\$')}\s*(?:\?\.|\.)\s*(?:${FAILURE_FIELD})`, 'g');
  return [...src.slice(from, to).matchAll(re)].map((m) => from + m.index!).filter((i) => !inSilentGuard(src, i));
}

/** For each JSX element `<Comp …>` in `src` between `from` and `to`, its
 * attributes written as `attr={name}`. */
function handedOn(src: string, [from, to]: [number, number]): Array<{ comp: string; attr: string; value: string }> {
  const found: Array<{ comp: string; attr: string; value: string }> = [];
  for (const m of src.slice(from, to).matchAll(/<([A-Z][\w$]*)\b/g)) {
    let end = from + m.index! + m[0].length;
    const start = end;
    while (end < to && src[end] !== '>') end = src[end] === '{' ? closing(src, end) : end + 1;
    for (const a of src.slice(start, end).matchAll(/\b([A-Za-z_$][\w$]*)\s*=\s*\{\s*([A-Za-z_$][\w$]*)\s*\}/g)) {
      found.push({ comp: m[1], attr: a[1], value: a[2] });
    }
  }
  return found;
}

/** For each component, the props it builds a line from when handed a query
 * (`LoadState`'s `query`), followed through components that pass the prop on
 * (`LLMSection` hands its `query` to `LoadState`). */
function queryFailureProps(sources: Record<string, string>): Map<string, Set<string>> {
  const props = new Map<string, Set<string>>();
  const add = (comp: string, prop: string) => {
    const set = props.get(comp) ?? new Set<string>();
    if (set.has(prop)) return false;
    props.set(comp, set.add(prop));
    return true;
  };
  const comps = Object.values(sources).map(withoutComments).flatMap((src) =>
    functionsIn(src)
      .filter((f) => /^[A-Z]/.test(f.name))
      .map((f) => ({ src, ...f })),
  );
  const isParam = (params: string, name: string) => new RegExp(`\\b${name.replace('$', '\\$')}\\b`).test(params);
  for (const { src, name, params, body } of comps) {
    for (const m of src.slice(...body).matchAll(new RegExp(String.raw`(?<![.\w$])([A-Za-z_$][\w$]*)\s*(?:\?\.|\.)\s*(?:${FAILURE_FIELD})`, 'g'))) {
      if (isParam(params, m[1]) && !inSilentGuard(src, body[0] + m.index!)) add(name, m[1]);
    }
  }
  for (let changed = true; changed; ) {
    changed = false;
    for (const { src, name, params, body } of comps) {
      for (const h of handedOn(src, body)) {
        if (props.get(h.comp)?.has(h.attr) && isParam(params, h.value) && add(name, h.value)) changed = true;
      }
    }
  }
  return props;
}

interface QueryReader {
  /** Where the call is. */
  index: number;
  /** Whether the toast stands aside for this reader (its `meta` is set, always
   * or at times). */
  standsAside: boolean;
  /** Whether this reader builds a line from the query's failure. */
  showsLine: boolean;
  /** Whether it stands aside only at times: by a condition, or only in place
   * of a first load. */
  atTimes: boolean;
}

/** Every reader of a query in `code` (comments already blanked): each call of
 * a query hook, and each `useQuery` whose result a component keeps. */
function queryReaders(code: string, hooks: Map<string, QueryHookMeta>, props: Map<string, Set<string>>): QueryReader[] {
  const readers: QueryReader[] = [];
  // What a call's result is kept in: a name, or a destructuring pattern. Null
  // when the result is not kept whole (`useX().data`, `return useQuery(…)`).
  const holder = (at: number, end: number) => {
    if (!/^[ \t]*(?:;|\r?\n|$)/.test(code.slice(end))) return null;
    return /(?:const|let)\s+([A-Za-z_$][\w$]*|\{[^{}]*\})\s*=\s*$/.exec(code.slice(Math.max(0, at - 400), at))?.[1] ?? null;
  };
  const showsLine = (held: string | null, at: number) => {
    if (!held) return false;
    const scope = scopeOf(code, at);
    if (!held.startsWith('{')) {
      if (failureReads(code, held, scope).length) return true;
      return handedOn(code, scope).some((h) => h.value === held && !!props.get(h.comp)?.has(h.attr));
    }
    // Destructured: the names the failure fields are kept under, read after
    // the call, other than as an object's key.
    const names = [...held.matchAll(/\b(isError|error|isLoadingError|isRefetchError)\b(?:\s*:\s*([A-Za-z_$][\w$]*))?/g)].map((m) => m[2] ?? m[1]);
    return names.some((n) =>
      [...code.slice(at, scope[1]).matchAll(new RegExp(String.raw`(?<![.\w$])${n.replace('$', '\\$')}\b`, 'g'))].some((m) => {
        const i = at + m.index!;
        const key = /[{,]\s*$/.test(code.slice(0, i)) && /^\s*:/.test(code.slice(i + n.length));
        return !key && !inSilentGuard(code, i);
      }),
    );
  };
  for (const [hook, meta] of hooks) {
    for (const m of code.matchAll(new RegExp(String.raw`(?<!function\s)\b${hook}\s*\(`, 'g'))) {
      const open = m.index! + m[0].length - 1;
      const end = closing(code, open);
      const args = code.slice(open + 1, end - 1);
      const optionOn = !!meta.option && new RegExp(String.raw`\b${meta.option}\s*:\s*(?!false\b)\S`).test(args);
      const optionValue = meta.option ? new RegExp(String.raw`\b${meta.option}\s*:\s*([^,}]+)`).exec(args)?.[1].trim() : undefined;
      readers.push({
        index: m.index!,
        standsAside: meta.when === 'always' || (meta.when === 'option' && optionOn),
        showsLine: showsLine(holder(m.index!, end), m.index!),
        atTimes: (meta.when === 'always' && !!meta.load) || (meta.when === 'option' && optionOn && optionValue !== 'true'),
      });
    }
  }
  for (let call = findQueryCall(code); call; call = findQueryCall(code, call.at + 1)) {
    const held = holder(call.at, call.end);
    if (!held) continue; // a hook's own `return useQuery(…)`
    const meta = queryMetaOf(call.options);
    readers.push({
      index: call.at,
      standsAside: meta.when !== 'never',
      showsLine: showsLine(held, call.at),
      atTimes: meta.text !== undefined && metaAtTimes(meta.text),
    });
  }
  return readers;
}

/** Each reader in `src` whose line the toast repeats, or whose failure is said
 * nowhere: `repeats` and `nowhere`, as line numbers. */
function queryLineProblems(src: string, hooks: Map<string, QueryHookMeta>, props = new Map<string, Set<string>>()) {
  const code = withoutComments(src);
  const readers = queryReaders(code, hooks, props);
  return {
    repeats: readers.filter((r) => r.showsLine && !r.standsAside).map((r) => lineOf(code, r.index)),
    nowhere: readers.filter((r) => r.standsAside && !r.showsLine).map((r) => lineOf(code, r.index)),
  };
}

/** Query lines the toast still repeats, or queries said nowhere, known and not
 * yet changed. The guard fails when one of these is fixed. */
const QUERY_NOT_YET: Record<string, string> = {};

/** Every file with a reader that stands aside only at times, and the test that
 * checks it both ways round: the line shows and the toast stands aside when the
 * condition holds (or before data), the toast speaks and no line does when it
 * does not (or behind data on screen). */
const CONDITIONAL_READERS: Record<string, string> = {
  'src/components/echo/EchoDataCard.tsx': 'src/pages/__tests__/loadFailuresOneMessage.test.tsx',
  'src/components/graph/GraphExplorer.tsx': 'src/pages/__tests__/loadFailuresConditions.test.tsx',
  'src/components/jobs/ReportPeekModal.tsx': 'src/pages/__tests__/loadFailuresConditions.test.tsx',
  'src/components/palette/PalettePanel.tsx': 'src/pages/__tests__/loadFailuresConditions.test.tsx',
  'src/components/security/TwoStepCard.tsx': 'src/pages/__tests__/loadFailuresConditions.test.tsx',
  'src/pages/AIModelsPage.tsx': 'src/pages/__tests__/loadFailuresConditions.test.tsx',
  'src/pages/AuthorPage.tsx': 'src/pages/__tests__/loadFailuresConditions.test.tsx',
  'src/pages/EchoPage.tsx': 'src/pages/__tests__/loadFailuresConditions.test.tsx',
  'src/pages/JobDetailPage.tsx': 'src/pages/__tests__/jobDetailLoadFailure.test.tsx',
  'src/pages/LibraryPage.tsx': 'src/pages/__tests__/loadFailuresOneMessage.test.tsx',
  'src/pages/VideoKnowledgePage.tsx': 'src/pages/__tests__/loadFailuresConditions.test.tsx',
};

/** Stand-ins for query hooks: one with no `meta`, one that always sets it, one
 * that sets it only in place of a first load, and one that takes
 * `inlineErrors`. */
const QUERY_HOOKS = new Map<string, QueryHookMeta>([
  ['useLoaded', { when: 'never' }],
  ['useShown', { when: 'always' }],
  ['useFirstLoad', { when: 'always', load: true }],
  ['useMaybe', { when: 'option', option: 'inlineErrors' }],
]);

/** The lines of the readers in `src` that stand aside only at times. */
function atTimesReaders(src: string, hooks: Map<string, QueryHookMeta>): number[] {
  const code = withoutComments(src);
  return queryReaders(code, hooks, new Map()).filter((r) => r.atTimes).map((r) => lineOf(code, r.index));
}

describe('the fourth guard: a query’s failure line stands alone', () => {
  const sources = import.meta.glob(['../../**/*.{ts,tsx}', '!**/__tests__/**', '!**/*.test.{ts,tsx}'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;
  const hooks = queryHooks(sources);
  const props = queryFailureProps(sources);

  it('knows how each query hook sets `meta`', () => {
    for (const name of ['useEchoFootprint', 'useLibraryGraph', 'useReportDocument']) {
      expect(hooks.get(name), name).toEqual({ when: 'always', load: true });
    }
    for (const name of ['useNotesList', 'useSavedSearches', 'useSavedSearchRuns', 'useDraftStatus', 'useVoiceSignals', 'useVoiceTest', 'useShares', 'useReportBody', 'useLLMSettings', 'useShelf', 'useQAHistoryChatHistory', 'useUsageSummary', 'useSessions', 'useAccountActivity', 'useChannelIntelligence', 'useKnowledgeSources', 'useAuthorOutputs', 'useAuthorOutput', 'useAuthorOutputContent', 'useAuthorOutputCitations']) {
      expect(hooks.get(name), name).toEqual({ when: 'always' });
    }
    for (const name of ['useEchoStatus', 'useEchoContext', 'useEchoConnectors', 'useShelves', 'useJobs', 'useJob', 'useJobTemplates', 'useOnboarding', 'useChannel', 'useChannels', 'useLibraryVideos', 'useKnowledge', 'useMfaStatus', 'useAuthorKinds', 'useOutputEstimate', 'useLLMEstimate']) {
      expect(hooks.get(name), name).toEqual({ when: 'option', option: 'inlineErrors' });
    }
    for (const name of ['useMe', 'useTags', 'useNotifications', 'useQuota', 'useVoiceTestPoll', 'useNotesForTarget']) {
      expect(hooks.get(name), name).toEqual({ when: 'never' });
    }
  });

  it('reads the query a section is handed', () => {
    expect(props.get('LoadState')).toEqual(new Set(['query']));
    expect(props.get('LLMSection')).toEqual(new Set(['query']));
  });

  it('finds no query line the toast repeats, and no query that stands aside where nothing says it', () => {
    const offenders = Object.entries(sources)
      .map(([file, src]) => [file.replace('../../', 'src/'), queryLineProblems(src, hooks, props)] as const)
      .filter(([, p]) => p.repeats.length > 0 || p.nowhere.length > 0)
      .map(([file, p]) => [file, `${p.repeats.length ? `repeats:${p.repeats.join(',')} ` : ''}${p.nowhere.length ? `nowhere:${p.nowhere.join(',')}` : ''}`.trim()] as const);
    expect(offenders.filter(([file]) => !(file in QUERY_NOT_YET))).toEqual([]);
    expect(offenders.map(([file]) => file).sort()).toEqual(Object.keys(QUERY_NOT_YET).sort());
  });

  it('names the page test that checks each reader standing aside only at times', () => {
    const tests = new Set(
      Object.keys(import.meta.glob('../../**/__tests__/*.test.{ts,tsx}')).map((file) => file.replace('../../', 'src/')),
    );
    const files = Object.entries(sources)
      .filter(([, src]) => atTimesReaders(src, hooks).length > 0)
      .map(([file]) => file.replace('../../', 'src/'))
      .sort();
    expect(files).toEqual(Object.keys(CONDITIONAL_READERS).sort());
    for (const [file, test] of Object.entries(CONDITIONAL_READERS)) expect(tests.has(test), `${file}: ${test}`).toBe(true);
  });

  it.each([
    ["const q = useMaybe({ inlineErrors: tab === 'a' });"],
    ["const q = useMaybe({ inlineErrors: 'load' });"],
    ["const q = useMaybe(id, { inlineErrors: open && !busy ? 'load' : false });"],
    ['const q = useFirstLoad();'],
    ['const q = useQuery({ queryKey: k, queryFn: f, meta: LOAD_ERRORS_SHOWN_HERE });'],
    ['const q = useQuery({ queryKey: k, queryFn: f, meta: queryErrorsMeta(rows.length === 0) });'],
    ['const q = useQuery({ queryKey: k, queryFn: f, meta: queryErrorsMeta(open) });'],
  ])('knows a reader that stands aside only at times: %s', (src) => {
    expect(atTimesReaders(src, QUERY_HOOKS)).toEqual([1]);
  });

  it.each([
    ['const q = useMaybe({ inlineErrors: true });'],
    ['const q = useMaybe({ inlineErrors: false });'],
    ['const q = useMaybe();'],
    ['const q = useShown();'],
    ['const q = useLoaded();'],
    ['const q = useQuery({ queryKey: k, queryFn: f, meta: ERRORS_SHOWN_HERE });'],
    ['const q = useQuery({ queryKey: k, queryFn: f, meta: queryErrorsMeta(true) });'],
    ['const q = useQuery({ queryKey: k, queryFn: f });'],
  ])('knows a reader that stands aside always or never: %s', (src) => {
    expect(atTimesReaders(src, QUERY_HOOKS)).toEqual([]);
  });

  it.each([
    ['const q = useLoaded();\nreturn <>{q.isError && <p role="alert">No.</p>}</>;'],
    ["const { data, isError } = useLoaded();\nif (isError) return <p>No.</p>;"],
    ["const { data, error: failure } = useLoaded();\nreturn failure ? <p>No.</p> : null;"],
    ["const q = useMaybe({ inlineErrors: false });\nconst line = q.isError ? inlineErrorMessage(q.error, 'No.') : null;"],
    ['const q = useMaybe();\nreturn q.status === \'error\' ? <p>No.</p> : null;'],
    ["const q = useQuery({ queryKey: k, queryFn: f });\nconst line = q.error ? 'No.' : null;"],
    ['const q = useQuery<Thing, AxiosError<{ detail?: string }>>({ queryKey: k, queryFn: f });\nreturn q.isError ? <p>No.</p> : null;'],
    ['const q = useLoaded();\nreturn <List isError={q.isError} />;'],
  ])('catches a line the toast repeats: %s', (src) => {
    expect(queryLineProblems(src, QUERY_HOOKS)).toEqual({ repeats: [1], nowhere: [] });
  });

  it('catches a line reached through a prop', () => {
    const src = 'function Box({ query }: P) {\n  return query.isError ? <p>No.</p> : null;\n}\nfunction Page() {\n  const q = useLoaded();\n  return <Box query={q} />;\n}';
    expect(queryLineProblems(src, QUERY_HOOKS, queryFailureProps({ src }))).toEqual({ repeats: [5], nowhere: [] });
  });

  it.each([
    ['const q = useShown();\nreturn <p>{q.data?.name}</p>;'],
    ['const name = useShown().data?.name;'],
    ['const q = useMaybe({ inlineErrors: true });\nif (q.isError) return null;'],
    ['const { isError } = useShown();\nif (isError || !data) return <Navigate to="/" replace />;'],
    ['const q = useQuery({ queryKey: k, queryFn: f, meta: ERRORS_SHOWN_HERE });\nreturn q.data ?? null;'],
  ])('catches a failure said nowhere: %s', (src) => {
    expect(queryLineProblems(src, QUERY_HOOKS)).toEqual({ repeats: [], nowhere: [1] });
  });

  it.each([
    ["const q = useShown();\nconst line = q.isError ? inlineErrorMessage(q.error, 'No.') : null;"],
    ["const q = useMaybe({ inlineErrors: tab === 'a' });\nconst line = q.isError ? 'No.' : null;"],
    ["const q = useMaybe({ inlineErrors: 'load' });\nreturn q.data ? <List /> : q.isError ? <p>No.</p> : null;"],
    ['const q = useMaybe();\nif (!enabled || q.isError) return null;'],
    ['const q = useLoaded();\nreturn <p>{q.data?.name}</p>;'],
    ['const { data, isLoading } = useLoaded();'],
    ["const { data, isError } = useShown();\nconst line = isError ? 'No.' : null;"],
    ['const q = useQuery({ queryKey: k, queryFn: f, meta: queryErrorsMeta(open) });\nreturn q.isError ? <p>No.</p> : null;'],
    ['export function useThing() {\n  return useQuery({ queryKey: k, queryFn: f, meta: ERRORS_SHOWN_HERE });\n}'],
    ['function A() {\n  const q = useShown();\n  return q.isError ? <p>No.</p> : null;\n}\nfunction B() {\n  const q = useLoaded();\n  return <p>{q.data}</p>;\n}'],
  ])('leaves alone %s', (src) => {
    expect(queryLineProblems(src, QUERY_HOOKS)).toEqual({ repeats: [], nowhere: [] });
  });

  it('leaves alone a line reached through a prop, when the reader stands aside', () => {
    const src = 'function Box({ query }: P) {\n  return query.isError ? <p>No.</p> : null;\n}\nfunction Page() {\n  const q = useShown();\n  return <Box query={q} />;\n}';
    expect(queryLineProblems(src, QUERY_HOOKS, queryFailureProps({ src }))).toEqual({ repeats: [], nowhere: [] });
  });
});

// ---------------------------------------------------------------------------
// The fifth guard: a poll says a run of failures once (T-3.4.1.27)
// ---------------------------------------------------------------------------
//
// The query client holds a poll to one toast per run of failures, and knows a
// poll by its readers' `refetchInterval` (`queryIsPolling`). So:
// - every `refetchInterval` in the app is listed in `POLLS`, by the function
//   that sets it, beside the tests that check that poll under the app's client
//   (each must exist and name the function); the guard fails on a poll not
//   listed, so a new one comes with its test. A `refetchInterval` is set as an
//   object key, written out (`refetchInterval: 5000`) or in short
//   (`{ queryKey, refetchInterval }`), in the options or in an object spread
//   into them, or assigned (`options.refetchInterval = 5000`); one taken out
//   of an object (`const { refetchInterval } = observer.options`, a
//   parameter) sets nothing;
// - nothing polls by a timer of its own: a `setInterval` whose callback asks a
//   query again (`refetch`, `refetchQueries`, `invalidateQueries` or
//   `fetchQuery`), written in place or a function it names, or a `setTimeout`
//   that does and sets itself again (a loop). The client could not tell such a
//   timer from a reader asking again, and it would toast every time. A
//   `setTimeout` that asks once (a debounce) is no poll.
//
// Mutation checks, run on 2026-11-10: taking `useImports` out of `POLLS`, or
// naming a test for the system page that does not exist, fails "lists every
// poll"; a hook with `setInterval(() => void q.refetch(), 5000)` in
// `useVideoFrames.ts` fails "finds no poll by a timer of its own". Matching
// only `refetchInterval:` fails the short-form and assignment rows of "reads
// where a poll is set", and reading the key without its pattern check fails
// the destructuring rows and "lists every poll" (`queryIsPolling` in the query
// client); reading only the callback written in place fails the named-callback
// rows of "knows a timer that polls", and reading only `setInterval` fails the
// loop rows.

/** The `{` that holds `index` in `code`, or -1. */
function openingBrace(code: string, index: number): number {
  let depth = 0;
  for (let i = index - 1; i >= 0; i -= 1) {
    if (code[i] === '}') depth += 1;
    else if (code[i] === '{' && depth-- === 0) return i;
  }
  return -1;
}

/** Whether the object around `index` is a pattern that takes values out
 * (`const { refetchInterval } = …`, a parameter), not one that sets them. */
function inPattern(code: string, index: number): boolean {
  const open = openingBrace(code, index);
  if (open === -1) return false;
  if (/\b(?:const|let|var)\s*$/.test(code.slice(Math.max(0, open - 12), open))) return true;
  const after = code.slice(closing(code, open));
  // Assigned from (`} = options`), or a parameter (`}) =>`, `}: Props) {`).
  return /^\s*(?::[^=;\n]*)?=(?![=>])/.test(after) || /^\s*(?::[^)\n]*)?\)\s*(?::[^=\n{]*)?(?:=>|\{)/.test(after);
}

/** Each function in `src` that sets a `refetchInterval`, by name. */
function pollSites(src: string): string[] {
  const code = withoutComments(src);
  const fns = functionsIn(code);
  const sets = /(?<![.\w$])refetchInterval(?=\s*[:,}])|\.refetchInterval\s*=(?![=>])/g;
  const names = [...code.matchAll(sets)]
    .filter((m) => m[0].startsWith('.') || !inPattern(code, m.index!))
    .map((m) => {
      const [from] = scopeOf(code, m.index!);
      return fns.find((f) => f.body[0] === from)?.name ?? '(module)';
    });
  return [...new Set(names)];
}

const ASKS_AGAIN = /\b(?:refetch|refetchQueries|invalidateQueries|fetchQuery)\b/;
const DEFINES = /\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=|\bfunction\s+([A-Za-z_$][\w$]*)\s*\(/g;

/** The first argument of the call whose `(` is at `open`. */
function firstArgument(code: string, open: number): string {
  const end = closing(code, open) - 1;
  let i = open + 1;
  while (i < end && code[i] !== ',') i = '({['.includes(code[i]) ? closing(code, i) : i + 1;
  return code.slice(open + 1, i).trim();
}

/** Where `src` polls by a timer of its own: a `setInterval` whose callback asks
 * a query again, or a `setTimeout` whose callback does and sets a timer again.
 * A callback that is a name is read where that function is defined. */
function timerPolls(src: string): number[] {
  const code = withoutComments(src);
  const defined = [...code.matchAll(DEFINES)].flatMap((m) => {
    const name = m[1] ?? m[2];
    const span = localFunction(code, name);
    return span && span[0] === m.index ? [{ name, span }] : [];
  });
  return [...code.matchAll(/\bset(Interval|Timeout)\s*\(/g)]
    .filter((m) => {
      const at = m.index!;
      const arg = firstArgument(code, at + m[0].length - 1);
      const named = /^[A-Za-z_$][\w$]*$/.test(arg) ? defined.find((d) => d.name === arg) : undefined;
      const callback = named ? code.slice(...named.span) : arg;
      if (!ASKS_AGAIN.test(callback)) return false;
      if (m[1] === 'Interval') return true;
      // A loop: the callback sets a timer again, or calls (or is) a function
      // this `setTimeout` is written in.
      return (
        /\bset(?:Timeout|Interval)\s*\(/.test(callback) ||
        defined.some(
          (d) =>
            at > d.span[0] &&
            at < d.span[1] &&
            (arg === d.name || new RegExp(String.raw`\b${d.name.replace('$', '\\$')}\s*\(`).test(arg)),
        )
      );
    })
    .map((m) => lineOf(code, m.index!));
}

const POLL_HOOKS_TEST = 'src/hooks/__tests__/pollHooks.test.tsx';

/** Every poll in the app (`file: function`), and the tests that check it says
 * a run of failures once, or stands aside for a line that says each one. */
const POLLS: Record<string, string[]> = {
  'src/hooks/useEcho.ts: useImports': [POLL_HOOKS_TEST],
  'src/hooks/useEcho.ts: useVoiceTestPoll': [POLL_HOOKS_TEST],
  'src/hooks/useJobs.ts: useJob': [POLL_HOOKS_TEST, 'src/pages/__tests__/jobDetailLoadFailure.test.tsx'],
  'src/hooks/useJobs.ts: useJobs': [POLL_HOOKS_TEST],
  'src/hooks/useNotifications.ts: useNotifications': [POLL_HOOKS_TEST],
  'src/hooks/useSavedSearches.ts: useSavedSearches': [POLL_HOOKS_TEST],
  'src/hooks/useSystemStatus.ts: useSystemStatus': [POLL_HOOKS_TEST, 'src/layouts/__tests__/healthPoll.test.tsx'],
  'src/hooks/useVideoFrames.ts: useVideoFrames': [POLL_HOOKS_TEST],
  'src/pages/SystemStatusPage.tsx: SystemStatusPage': ['src/pages/__tests__/systemStatusPage.test.tsx'],
};

describe('the fifth guard: a poll says a run of failures once', () => {
  const sources = import.meta.glob(['../../**/*.{ts,tsx}', '!**/__tests__/**', '!**/*.test.{ts,tsx}'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;
  const tests = import.meta.glob('../../**/__tests__/*.test.{ts,tsx}', {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;

  it('lists every poll beside the tests that check it', () => {
    const found = Object.entries(sources)
      .flatMap(([file, src]) => pollSites(src).map((name) => `${file.replace('../../', 'src/')}: ${name}`))
      .sort();
    expect(found).toEqual(Object.keys(POLLS).sort());
    for (const [site, files] of Object.entries(POLLS)) {
      const name = site.split(': ')[1];
      for (const file of files) {
        const test = tests[file.replace('src/', '../../')];
        expect(test, `${site}: ${file}`).toBeDefined();
        expect(test.includes(name), `${file} names ${name}`).toBe(true);
      }
    }
  });

  it('finds no poll by a timer of its own', () => {
    const offenders = Object.entries(sources)
      .map(([file, src]) => [file.replace('../../', 'src/'), timerPolls(src)] as const)
      .filter(([, lines]) => lines.length > 0);
    expect(offenders).toEqual([]);
  });

  it.each([
    ['export function useThing() {\n  return useQuery({ queryKey: k, queryFn: f, refetchInterval: 5000 });\n}', ['useThing']],
    ['function Page() {\n  const q = useQuery({ queryKey: k, queryFn: f, refetchInterval: (q) => (q.state.data ? 3000 : false) });\n}', ['Page']],
    ['// refetchInterval: 5000 in a comment\nexport function useThing() {\n  return useQuery({ queryKey: k, queryFn: f });\n}', []],
    ['export function useThing(busy: boolean) {\n  const refetchInterval = busy ? 4000 : false;\n  return useQuery({ queryKey: k, queryFn: f, refetchInterval });\n}', ['useThing']],
    ['function Page() {\n  return useQuery({ queryKey: k, queryFn: f, refetchInterval\n  });\n}', ['Page']],
    ['function Page() {\n  const opts = { queryKey: k, queryFn: f, refetchInterval: 5000 };\n  return useQuery({ ...opts });\n}', ['Page']],
    ['function Page() {\n  const opts: Options = { queryKey: k, queryFn: f };\n  opts.refetchInterval = 5000;\n  return useQuery(opts);\n}', ['Page']],
    ['export function isPolling(o: Options) {\n  const { enabled, refetchInterval } = o;\n  return enabled && refetchInterval;\n}', []],
    ['export function isPolling(o: Options) {\n  const { refetchInterval: every }: Options = o;\n  return every === o.refetchInterval;\n}', []],
    ['function Poller({ refetchInterval }: Props) {\n  return null;\n}', []],
    ['const pick = ({ queryKey, refetchInterval }) => queryKey;', []],
  ])('reads where a poll is set: %s', (src, names) => {
    expect(pollSites(src)).toEqual(names);
  });

  it.each([
    ['function Page() {\n  useEffect(() => {\n    const id = setInterval(() => void q.refetch(), 5000);\n  }, []);\n}', [3]],
    ['const id = window.setInterval(() => qc.invalidateQueries({ queryKey: k }), 4000);', [1]],
    ['const id = window.setInterval(() => WSClient.send(socket, "ping"), 30000);', []],
    ['const t = setTimeout(() => void qc.invalidateQueries({ queryKey: k }), 500);', []],
    ['function Page() {\n  const tick = () => void q.refetch();\n  useEffect(() => {\n    const id = setInterval(tick, 5000);\n  }, []);\n}', [4]],
    ['function tick() {\n  void qc.invalidateQueries({ queryKey: k });\n}\nconst id = setInterval(tick, 5000);', [4]],
    ['const id = setInterval(q.refetch, 5000);', [1]],
    ['function Page() {\n  useEffect(() => {\n    const tick = () => {\n      void q.refetch();\n      id = setTimeout(tick, 5000);\n    };\n    let id = setTimeout(tick, 5000);\n  }, []);\n}', [5, 7]],
    ['function Page() {\n  const schedule = () => {\n    id = setTimeout(() => {\n      void qc.invalidateQueries({ queryKey: k });\n      schedule();\n    }, 5000);\n  };\n}', [3]],
    ['function Page() {\n  const later = () => void qc.invalidateQueries({ queryKey: k });\n  const t = setTimeout(later, 500);\n}', []],
    ['function Page() {\n  const tick = () => WSClient.send(socket, "ping");\n  const id = setInterval(tick, 30000);\n}', []],
  ])('knows a timer that polls from one that does not: %s', (src, lines) => {
    expect(timerPolls(src)).toEqual(lines);
  });
});
