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
  // Each builds a line from a mutation's `isError` / `error` beside the global
  // toast. Found once the guard read lines from a mutation's state (T-3.4.1.22),
  // after that task was filed, and left for one of their own.
  'src/components/echo/DraftEditor.tsx': 'found by the state reading, not yet in a task',
  'src/components/frames/VideoFramesPanel.tsx': 'found by the state reading, not yet in a task',
  'src/components/library/PasteUrlsForm.tsx': 'found by the state reading, not yet in a task',
  'src/components/notes/NotesPanel.tsx': 'found by the state reading, not yet in a task',
  'src/components/savedSearches/PinQuestionButton.tsx': 'found by the state reading, not yet in a task',
  'src/pages/NotesPage.tsx': 'found by the state reading, not yet in a task',
  'src/pages/SavedSearchesPage.tsx': 'found by the state reading, not yet in a task',
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
