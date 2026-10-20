import { describe, expect, it } from 'vitest';
import { computeReadiness } from '../echoReadiness';
import {
  cardContext,
  draftGateView,
  historyRefHref,
  missingParts,
  readinessLine,
  requestErrorLine,
  shortcutLabel,
  voiceMatchLine,
} from '../echoPanel';

const status = (over: Partial<Parameters<typeof computeReadiness>[0]> = {}) =>
  computeReadiness(
    { ready: false, total_rows: 99, distinct_sources: 3, has_personality_trait: true, threshold_total: 100, threshold_sources: 3, ...over },
    1,
  );

describe('readiness in words', () => {
  it('names only what is missing, with counts', () => {
    expect(missingParts(status())).toEqual(['1 more fact']);
    expect(readinessLine(status({ total_rows: 10, distinct_sources: 1, has_personality_trait: false }))).toBe(
      '14% ready. Still needs 90 more facts, 2 more sources and a personality trait.',
    );
  });

  it('says ready when the backend does', () => {
    expect(readinessLine(status({ ready: true, total_rows: 100 }))).toBe('Echo is ready.');
  });

  it('names the unmet domains once the server sends them, not the v1 gates (S-3.5.1)', () => {
    const domain = (key: string, label: string, met: boolean, progress: number) => ({
      key, domain: 1, label, status: met ? 'met' : 'in_progress', met, progress, criteria: [], summary: '', missing: null, details: {},
    });
    const v2 = status({
      total_rows: 10, distinct_sources: 1, has_personality_trait: false, progress: 0.5,
      domains: [
        domain('facts', 'Facts about you', false, 0.4),
        domain('activity', 'What you do', true, 1),
        domain('signals', 'How you think', true, 1),
        domain('voice', 'How you write', false, 0.1),
        domain('shares', 'What you share', true, 1),
      ],
    });
    expect(missingParts(v2)).toEqual(['facts about you', 'writing of your own']);
    expect(readinessLine(v2)).toBe('50% ready. Still needs more facts about you and writing of your own.');
  });
});

describe('the speak-as-me gate', () => {
  const ready = status({ ready: true, total_rows: 100 });

  it('reports a missing endpoint as not shipped, and any other failure as unknown', () => {
    expect(draftGateView(undefined, { response: { status: 404 } }, ready)).toMatchObject({ available: false, title: 'Not on this install yet' });
    expect(draftGateView(undefined, { response: { status: 500 } }, ready).title).toBe('Could not check');
    expect(draftGateView(undefined, null, ready).title).toBe('Checking…');
  });

  it('offers the composer only when enabled', () => {
    expect(draftGateView({ enabled: true, state: 'enabled' }, null, ready).available).toBe(true);
    expect(draftGateView({ enabled: false, state: 'enabled' }, null, ready).available).toBe(false);
  });

  it('explains each gate, preferring the server’s own reasons', () => {
    const notReady = draftGateView({ enabled: false, state: 'not_ready' }, null, status({ has_personality_trait: false }));
    expect(notReady.lines).toEqual(['Still needs 1 more fact, a personality trait.']);
    expect(notReady.action?.href).toBe('/echo');
    const test = draftGateView({ enabled: false, state: 'voice_test_needed', notes: 41, notes_needed: 40 }, null, ready);
    expect(test.title).toBe('Your voice test comes first');
    expect(test.lines.some((l) => l.includes('notes of the'))).toBe(false);
    expect(draftGateView({ enabled: false, state: 'voice_test_failed', reasons: ['Try again after 10 more notes.'] }, null, ready).lines).toEqual([
      'Try again after 10 more notes.',
    ]);
    expect(draftGateView({ enabled: false, state: 'paused_by_operator' }, null, ready).title).toBe('Not switched on for you');
  });
});

describe('small labels', () => {
  it('names the shortcut per platform', () => {
    expect(shortcutLabel(true)).toBe('⌘⇧E');
    expect(shortcutLabel(false)).toBe('Ctrl+Shift+E');
  });

  it('words request failures', () => {
    expect(requestErrorLine({ response: { status: 429 } })).toContain('limit');
    expect(requestErrorLine(new Error('offline'))).toBe('Could not reach the server.');
  });

  it('reads a voice-match score on S-3.4.1’s 0 to 100 scale', () => {
    expect(voiceMatchLine(82.4)).toBe('Sounds like you: 82%');
    expect(voiceMatchLine(1)).toBe('Sounds like you: 1%');
    expect(voiceMatchLine(140)).toBe('Sounds like you: 100%');
    expect(voiceMatchLine(null)).toBeNull();
  });

  it('links a history citation to where it was asked', () => {
    expect(historyRefHref({ source_type: 'job', exchange_id: 'e', job_id: 'j1' })).toBe('/jobs/j1');
    expect(historyRefHref({ source_type: 'history', exchange_id: 'e2' })).toBe('/qa-history#exchange-e2');
  });
});

describe('the cards context for the page in view', () => {
  it('reads a run, its report, a knowledge page, else the library', () => {
    expect(cardContext('/jobs/abc-1')).toBe('job:abc-1');
    expect(cardContext('/reports/abc-1')).toBe('job:abc-1');
    expect(cardContext('/knowledge/dQw4w9WgXcQ')).toBe('document:dQw4w9WgXcQ');
    expect(cardContext('/jobs')).toBe('library');
    expect(cardContext('/library/qa')).toBe('library');
  });
});

describe('the gate from S-3.4.1 blockers', () => {
  const ready = status({ ready: true, total_rows: 100 });
  const NOT_READY = { code: 'not_ready', message: 'Echo needs more to go on first, in 5 of 5 areas. Facts about you: …' };

  it('titles by the first blocker and shortens the not-ready wall of text', () => {
    const view = draftGateView(
      { enabled: false, state: 'install_off', blockers: [{ code: 'install_off', message: 'Speak as me is turned off on this install.' }, NOT_READY] },
      null,
      ready,
    );
    expect(view.title).toBe('Turned off on this install');
    expect(view.lines).toEqual([
      'Speak as me is turned off on this install.',
      'Echo needs more to go on first: the line above says what is missing.',
    ]);
    expect(view.action?.href).toBe('/echo');
  });

  it('points to notes for the voice test, and says when today’s drafts are used', () => {
    const test = draftGateView(
      { enabled: false, state: 'voice_test_required', blockers: [{ code: 'voice_test_required', message: 'It needs 40 of your notes; you have 3.' }] },
      null,
      ready,
    );
    expect(test.title).toBe('Your voice test comes first');
    expect(test.lines).toEqual(['It needs 40 of your notes; you have 3.']);
    expect(test.action?.href).toBe('/notes');
    const cap = draftGateView({ enabled: false, state: 'daily_cap', blockers: [{ code: 'daily_cap', message: 'You have used today’s 20 drafts.' }] }, null, ready);
    expect(cap.title).toBe('That was today’s last draft');
    expect(cap.action).toBeUndefined();
  });
});
