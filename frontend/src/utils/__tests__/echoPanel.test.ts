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

  it('reads a voice-match score either as a fraction or a percentage', () => {
    expect(voiceMatchLine(0.824)).toBe('82% like you');
    expect(voiceMatchLine(91)).toBe('91% like you');
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
