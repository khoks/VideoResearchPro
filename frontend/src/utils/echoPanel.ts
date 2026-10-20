/*
 * Pure logic for the Echo panel (S-3.8.1): the shortcut's label, readiness in
 * one line, the "speak as me" gate in words, and error wording. No React.
 */

import type { DraftGate } from '../services/echoApi';
import type { Readiness } from './echoReadiness';

/** The chord the panel opens with: Mod-Shift-E (not Cmd-E, which is macOS's
 * "Use Selection for Find"; see the L3 plan, Domain 4). */
export const ECHO_SHORTCUT = 'mod+shift+e';

export function shortcutLabel(mac: boolean): string {
  return mac ? '⌘⇧E' : 'Ctrl+Shift+E';
}

function plural(n: number, one: string, many: string): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/** What each unmet readiness domain (S-3.5.1) still needs, after "more". */
const DOMAIN_NEEDS: Record<string, string> = {
  facts: 'facts about you',
  activity: 'activity history',
  signals: 'signals of how you think',
  voice: 'writing of your own',
  shares: 'shares',
};

/** What readiness still needs, as short phrases: the unmet domains when the
 * server sends them ("facts about you"), else the v1 gates ("12 more facts"). */
export function missingParts(readiness: Readiness): string[] {
  if (readiness.domains) {
    return readiness.domains.filter((d) => !d.met).map((d) => DOMAIN_NEEDS[d.key] ?? d.label.toLowerCase());
  }
  const out: string[] = [];
  for (const p of readiness.parts) {
    if (p.met) continue;
    if (p.gate === 'rows') out.push(plural(Math.max(0, p.target - p.current), 'more fact', 'more facts'));
    else if (p.gate === 'sources') out.push(plural(Math.max(0, p.target - p.current), 'more source', 'more sources'));
    else if (p.gate === 'personality') out.push('a personality trait');
  }
  return out;
}

/** "Echo is ready." or "40% ready. Still needs more facts about you and shares."
 * (v1: "40% ready. Still needs 12 more facts and a personality trait.") */
export function readinessLine(readiness: Readiness): string {
  if (readiness.ready) return 'Echo is ready.';
  const missing = missingParts(readiness);
  if (!missing.length) return `${readiness.percent}% ready.`;
  const list = missing.length === 1 ? missing[0] : `${missing.slice(0, -1).join(', ')} and ${missing[missing.length - 1]}`;
  return `${readiness.percent}% ready. Still needs ${readiness.domains ? 'more ' : ''}${list}.`;
}

/** The HTTP status of a failed request, if it has one. */
export function httpStatus(error: unknown): number | null {
  const status = (error as { response?: { status?: unknown } } | null)?.response?.status;
  return typeof status === 'number' ? status : null;
}

export interface GateView {
  /** Whether the draft composer is offered. */
  available: boolean;
  title: string;
  lines: string[];
  action?: { label: string; href: string };
}

const TEST_EXPLAINED =
  'Speak as me switches on for you after a blind test: you are shown pairs of texts and pick the one you wrote. It passes when you cannot reliably tell Echo’s draft from your own writing.';

/**
 * The "speak as me" gate (D-100) in words. `gate` is the status read, `error`
 * its failure: a 404 means the feature has not shipped on this install.
 */
export function draftGateView(gate: DraftGate | undefined, error: unknown, readiness: Readiness | null): GateView {
  const status = httpStatus(error);
  if (status === 404) {
    return {
      available: false,
      title: 'Not on this install yet',
      lines: ['Speak as me drafts replies in your voice, from what Echo knows about you. It appears here once it ships.'],
    };
  }
  if (error) {
    return { available: false, title: 'Could not check', lines: ['Echo could not say whether drafting is on for you. Try again in a moment.'] };
  }
  if (!gate) return { available: false, title: 'Checking…', lines: [] };
  if (gate.enabled) return { available: true, title: 'Draft as me', lines: [] };
  if (gate.blockers?.length) return blockersView(gate.blockers);

  const reasons = (gate.reasons ?? []).filter(Boolean);
  const notes =
    typeof gate.notes === 'number' && typeof gate.notes_needed === 'number' && gate.notes < gate.notes_needed
      ? [`You have ${plural(gate.notes, 'note', 'notes')} of the ${gate.notes_needed} the test needs.`]
      : [];
  switch (gate.state) {
    case 'not_ready': {
      const missing = readiness ? missingParts(readiness) : [];
      return {
        available: false,
        title: 'Echo is not ready yet',
        lines: reasons.length ? reasons : missing.length ? [`Still needs ${missing.join(', ')}.`] : ['Echo needs more of you first.'],
        action: { label: 'See what is missing', href: '/echo' },
      };
    }
    case 'voice_test_needed':
      return {
        available: false,
        title: 'Your voice test comes first',
        lines: [...(reasons.length ? reasons : [TEST_EXPLAINED]), ...notes],
        action: { label: 'Write a note', href: '/notes' },
      };
    case 'voice_test_failed':
      return {
        available: false,
        title: 'Your voice test has not passed yet',
        lines: reasons.length ? reasons : ['You could still tell Echo’s drafts from your own writing. More of your own words will help; the test can be taken again.'],
      };
    default:
      return { available: false, title: 'Not switched on for you', lines: reasons.length ? reasons : [TEST_EXPLAINED] };
  }
}

const BLOCKER_TITLE: Record<string, string> = {
  install_off: 'Turned off on this install',
  not_ready: 'Echo is not ready yet',
  voice_test_required: 'Your voice test comes first',
  voice_test_failed: 'Your voice test has not passed yet',
  daily_cap: 'That was today’s last draft',
};

/**
 * S-3.4.1's own blockers, first one as the title. The not-ready message
 * repeats every unmet domain, which the readiness line above the tabs
 * already names, so it is shortened here.
 */
function blockersView(blockers: Array<{ code: string; message: string }>): GateView {
  const lines = blockers.map((b) =>
    b.code === 'not_ready' ? 'Echo needs more to go on first: the line above says what is missing.' : b.message,
  );
  const codes = new Set(blockers.map((b) => b.code));
  const action = codes.has('not_ready')
    ? { label: 'See what is missing', href: '/echo' }
    : codes.has('voice_test_required')
      ? { label: 'Write a note', href: '/notes' }
      : undefined;
  return { available: false, title: BLOCKER_TITLE[blockers[0].code] ?? 'Not switched on for you', lines, action };
}

/** Words for a failed ask or draft. */
export function requestErrorLine(error: unknown): string {
  const status = httpStatus(error);
  if (status === 429) return 'You have reached today’s limit for this. It resets tomorrow.';
  if (status === 403) return 'Your plan does not include this.';
  if (status === 409) return 'Not available for you yet.';
  if (status === null) return 'Could not reach the server.';
  return 'Something went wrong. Try again.';
}

/** Where a Q&A-history citation leads, and what it is called (the same
 * mapping as the Q&A history page). */
export function historyRefHref(ref: { source_type: string; exchange_id: string; job_id?: string | null }): string {
  if (ref.source_type === 'job' && ref.job_id) return `/jobs/${ref.job_id}`;
  if (ref.source_type === 'library') return '/library/qa';
  return `/qa-history#exchange-${ref.exchange_id}`;
}

export function historyRefLabel(sourceType: string): string {
  if (sourceType === 'job') return 'Job Q&A';
  if (sourceType === 'library') return 'Library Q&A';
  return 'Q&A history';
}

/** "Sounds like you: 82%" (S-3.4.1 scores 0 to 100, the Echo page's
 * wording), or null when the score is missing. */
export function voiceMatchLine(score: number | null | undefined): string | null {
  if (typeof score !== 'number' || !Number.isFinite(score)) return null;
  return `Sounds like you: ${Math.max(0, Math.min(100, Math.round(score)))}%`;
}

/** The suggestions context for the page in view (S-3.8.2): a run or its
 * report, a source's knowledge page, else the library. */
export function cardContext(pathname: string): string {
  const run = pathname.match(/^\/(?:jobs|reports)\/([\w-]+)\/?$/);
  if (run) return `job:${run[1]}`;
  const doc = pathname.match(/^\/knowledge\/([\w:-]+)\/?$/);
  if (doc) return `document:${doc[1]}`;
  return 'library';
}

/** What each card kind is called in the panel's card settings. */
export const CARD_KIND_LABELS: Record<string, string> = {
  saved_search: 'Saved searches whose answer changed',
  shares: 'News from your shares inbox',
  questions: 'Questions for the page you are on',
};
