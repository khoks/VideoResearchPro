/**
 * S-3.5.1: the readiness view shows each domain's missing piece in words, a
 * blocked connector as "not connected" with its reason, and whether the user
 * can take the voice test; the percentage follows the server's progress.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ReadinessDomains } from '../ReadinessDomains';
import { computeReadiness } from '../../../utils/echoReadiness';
import type { EchoStatus, ReadinessDomain } from '../../../services/echoApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const crit = (key: string, current: number, target: number) => ({
  key, label: key, current, target, met: current >= target, fraction: Math.min(1, current / target),
});

const DOMAINS: ReadinessDomain[] = [
  { key: 'facts', domain: 1, label: 'Facts about you', status: 'in_progress', met: false, progress: 0.4,
    criteria: [crit('facts', 12, 30)], summary: '12 facts you wrote, across 2 kinds.',
    missing: 'To finish: write 18 more facts about yourself and cover 1 more kind.', details: {} },
  { key: 'activity', domain: 2, label: 'What you do', status: 'not_connected', met: false, progress: 0,
    criteria: [crit('events', 0, 200)], summary: 'No activity yet.',
    missing: 'Not connected yet: connect a service (GitHub) or import an export to start.',
    details: { sources: [
      { name: 'github', label: 'GitHub', kind: 'connector', status: 'connected', available: true, reason: null, events: 412 },
      { name: 'youtube_likes', label: 'YouTube likes', kind: 'connector', status: 'not_connected', available: false,
        reason: "Waits on this install's Google connector OAuth client (S-3.2.2).", events: 0 },
    ] } },
  { key: 'voice', domain: 3, label: 'How you write', status: 'met', met: true, progress: 1,
    criteria: [crit('floor', 1, 1)], summary: '31 pieces of your own writing in Latin script (2,410 words).', missing: null,
    details: { voice_test: { eligible: false, notes: 31, notes_needed: 9 },
               stability: { measured: false, spread: null, max: 0.05, reason: 'The notes index is off on this install, so stability is not measured.' } } },
];

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('ReadinessDomains', () => {
  it('says what is missing, per domain, in words', () => {
    act(() => root.render(<MemoryRouter><ReadinessDomains domains={DOMAINS} /></MemoryRouter>));
    const facts = host.querySelector('[data-domain="facts"]')!;
    expect(facts.textContent).toContain('write 18 more facts about yourself');
    expect(facts.textContent).toContain('On the way');
    const activity = host.querySelector('[data-domain="activity"]')!;
    expect(activity.textContent).toContain('Not connected');
    expect(activity.querySelector('[data-source="github"]')!.textContent).toContain('GitHub · connected · 412 events');
    expect(activity.querySelector('[data-source="youtube_likes"]')!.textContent).toContain(
      "YouTube likes · not connected — Waits on this install's Google connector OAuth client",
    );
    const voice = host.querySelector('[data-domain="voice"]')!;
    expect(voice.textContent).toContain('Done');
    expect(voice.querySelector('[data-voice-test]')!.textContent).toContain('after 40 notes (9 to go)');
    expect(voice.textContent).toContain('stability is not measured');
  });
});

describe('computeReadiness with domains', () => {
  const base: EchoStatus = {
    ready: false, total_rows: 7, distinct_sources: 2, has_personality_trait: false,
    threshold_total: 100, threshold_sources: 3,
  };
  it('uses the server progress and carries the domains', () => {
    const r = computeReadiness({ ...base, progress: 0.4666, domains: DOMAINS }, 1);
    expect(r.percent).toBe(47);
    expect(r.domains).toHaveLength(3);
  });
  it('stays below 100 until the server says ready, and falls back without domains', () => {
    expect(computeReadiness({ ...base, progress: 1, domains: DOMAINS }, 1).percent).toBe(99);
    expect(computeReadiness({ ...base, ready: true, progress: 1, domains: DOMAINS }, 1).percent).toBe(100);
    expect(computeReadiness(base, 1).domains).toBeNull();
  });
});
