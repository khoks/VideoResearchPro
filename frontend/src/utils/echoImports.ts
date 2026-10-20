/*
 * Pure logic for Echo's export-file imports (S-3.7.5). No React.
 *
 * The backend detects the format and parses the file; these helpers decide
 * how an import and the shares it wrote read on the page.
 */

const IMPORTER_LABELS: Record<string, string> = {
  whatsapp: 'WhatsApp chat',
  google_keep: 'Google Keep notes',
  google_takeout: 'Google Takeout',
  spotify_export: 'Spotify history',
  goodreads_export: 'Goodreads library',
  letterboxd_export: 'Letterboxd films',
  strava_export: 'Strava activities',
  apple_health_export: 'Apple Health',
};

/** What one event is called, per importer, for the counts line. */
const EVENT_NOUN: Record<string, [string, string]> = {
  google_takeout: ['YouTube history entry', 'YouTube history entries'],
  spotify_export: ['play', 'plays'],
  goodreads_export: ['book', 'books'],
  letterboxd_export: ['film entry', 'film entries'],
  strava_export: ['activity', 'activities'],
};

/** Importers that write shares (and so have authorship to report). */
const SHARE_IMPORTERS = new Set(['whatsapp', 'google_keep', 'google_takeout']);

export function importerLabel(name: string): string {
  return IMPORTER_LABELS[name] ?? name.replace(/_/g, ' ');
}

const STATUS_LABELS: Record<string, string> = {
  importing: 'Importing',
  embedding: 'Indexing',
  done: 'Imported',
  failed: 'Needs a retry',
  deleting: 'Undoing',
};

export function importStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

function n(counts: Record<string, number | undefined>, key: string): number {
  const v = counts[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : 0;
}

function plural(count: number, one: string, many: string): string {
  return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}

/**
 * One line saying what an import stored and what it deliberately did not:
 * "48 items: 20 in your words, 28 context only · 12 of the other side's
 * messages not stored".
 */
export function importCountsLine(importer: string, counts: Record<string, number | undefined>): string {
  const shares = n(counts, 'shares');
  const unit = importer === 'whatsapp' ? ['turn', 'turns'] : ['note', 'notes'];
  const parts: string[] = [];
  if (SHARE_IMPORTERS.has(importer) && (shares || !n(counts, 'events'))) {
    parts.push(`${plural(shares, unit[0], unit[1])}: ${n(counts, 'own_words').toLocaleString()} in your words, ${n(counts, 'context_only').toLocaleString()} context only`);
  }
  const events = n(counts, 'events');
  const held = n(counts, 'events_already_held');
  if (events || held || EVENT_NOUN[importer]) {
    const noun = EVENT_NOUN[importer] ?? ['event', 'events'];
    parts.push(`${plural(events, noun[0], noun[1])} recorded`);
    if (held) parts.push(`${held.toLocaleString()} already in Echo`);
  }
  const facts = n(counts, 'facts');
  if (facts) parts.push(`${plural(facts, 'routine summary', 'routine summaries')}`);
  const privateSkipped = n(counts, 'private_session_skipped');
  if (privateSkipped) parts.push(`${plural(privateSkipped, 'private-session play', 'private-session plays')} left out`);
  const ads = n(counts, 'ads_skipped');
  if (ads) parts.push(`${plural(ads, 'ad', 'ads')} left out`);
  const redacted = n(counts, 'redacted_messages');
  if (redacted) parts.push(`${plural(redacted, "of the other side's messages", "of the other side's messages")} not stored`);
  const trashed = n(counts, 'skipped_trashed');
  if (trashed) parts.push(`${plural(trashed, 'trashed note', 'trashed notes')} left out`);
  return parts.join(' · ');
}

/** Embedding progress, for an import still being indexed. */
export function importProgress(counts: Record<string, number | undefined>): string | null {
  const shares = n(counts, 'shares');
  if (!shares) return null;
  return `${n(counts, 'embedded').toLocaleString()} of ${shares.toLocaleString()} indexed`;
}

/**
 * Where an imported share came from, for its card in the inbox:
 * "WhatsApp chat with Asha · Asha" or "Keep · Tariff thoughts · Essays".
 */
export function importedProvenance(imported: Record<string, unknown> | null | undefined): string | null {
  if (!imported) return null;
  const importer = String(imported.importer ?? '');
  if (importer === 'whatsapp') {
    const chat = String(imported.chat ?? '').trim();
    const sender = String(imported.sender ?? '').trim();
    return [chat ? `WhatsApp chat with ${chat}` : 'WhatsApp chat', sender].filter(Boolean).join(' · ');
  }
  if (importer === 'google_keep') {
    const title = String(imported.title ?? '').trim();
    const labels = Array.isArray(imported.labels) ? imported.labels.map(String).filter(Boolean) : [];
    return ['Keep', title || null, labels.length ? labels.join(', ') : null].filter(Boolean).join(' · ');
  }
  return importer ? importerLabel(importer) : null;
}

/** The browser's time zone, sent so chat times (the phone's local time)
 * are stored correctly. Null when the browser cannot say. */
export function browserTimeZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

/** Files the picker offers. Detection happens on the server either way. */
export const IMPORT_ACCEPT = '.txt,.zip,.json';
