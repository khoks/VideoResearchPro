import { describe, expect, it } from 'vitest';
import {
  importCountsLine,
  importedProvenance,
  importerLabel,
  importProgress,
  importStatusLabel,
} from '../echoImports';

describe('importerLabel and importStatusLabel', () => {
  it('names the known importers and statuses, and degrades for new ones', () => {
    expect(importerLabel('whatsapp')).toBe('WhatsApp chat');
    expect(importerLabel('google_keep')).toBe('Google Keep notes');
    expect(importerLabel('spotify_export')).toBe('Spotify history');
    expect(importerLabel('mastodon_export')).toBe('mastodon export');
    expect(importStatusLabel('embedding')).toBe('Indexing');
    expect(importStatusLabel('failed')).toBe('Needs a retry');
    expect(importStatusLabel('something_new')).toBe('something_new');
  });
});

describe('importCountsLine', () => {
  it('says what was stored and, for a redacted chat, what was not', () => {
    expect(
      importCountsLine('whatsapp', { shares: 2, own_words: 2, context_only: 0, redacted_turns: 3, redacted_messages: 4 }),
    ).toBe("2 turns: 2 in your words, 0 context only · 4 of the other side's messages not stored");
  });

  it('counts Keep notes as notes and mentions trashed ones left out', () => {
    expect(importCountsLine('google_keep', { shares: 1, own_words: 1, context_only: 0, skipped_trashed: 1 })).toBe(
      '1 note: 1 in your words, 0 context only · 1 trashed note left out',
    );
  });

  it('counts the event imports in their own nouns, and what Echo already held', () => {
    expect(importCountsLine('spotify_export', { events: 3, events_already_held: 2, private_session_skipped: 1 })).toBe(
      '3 plays recorded · 2 already in Echo · 1 private-session play left out',
    );
    expect(importCountsLine('google_takeout', { shares: 2, own_words: 2, context_only: 0, events: 5, ads_skipped: 1 })).toBe(
      '2 notes: 2 in your words, 0 context only · 5 YouTube history entries recorded · 1 ad left out',
    );
    expect(importCountsLine('apple_health_export', { facts: 3 })).toBe('3 routine summaries');
    expect(importCountsLine('strava_export', { events: 0 })).toBe('0 activities recorded');
  });

  it('survives missing counts', () => {
    expect(importCountsLine('whatsapp', {})).toBe('0 turns: 0 in your words, 0 context only');
  });
});

describe('importProgress', () => {
  it('reports indexing progress, or nothing for an empty import', () => {
    expect(importProgress({ shares: 1200, embedded: 256 })).toBe(`256 of ${(1200).toLocaleString()} indexed`);
    expect(importProgress({ shares: 0 })).toBeNull();
  });
});

describe('importedProvenance', () => {
  it('names the chat and the sender of a WhatsApp turn', () => {
    expect(importedProvenance({ importer: 'whatsapp', chat: 'Asha', sender: 'Asha' })).toBe('WhatsApp chat with Asha · Asha');
    expect(importedProvenance({ importer: 'whatsapp', sender: 'Rahul' })).toBe('WhatsApp chat · Rahul');
  });

  it('gives a Keep note its title and labels', () => {
    expect(importedProvenance({ importer: 'google_keep', title: 'Tariff thoughts', labels: ['Essays', 'Economics'] })).toBe(
      'Keep · Tariff thoughts · Essays, Economics',
    );
    expect(importedProvenance({ importer: 'google_keep', title: null, labels: [] })).toBe('Keep');
  });

  it('says nothing for a share that was not imported', () => {
    expect(importedProvenance(null)).toBeNull();
    expect(importedProvenance(undefined)).toBeNull();
  });
});
