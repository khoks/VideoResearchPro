import type { Cadence } from '../services/savedSearchesApi';

export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/** The reader's own zone, so "09:00" means their 09:00. */
export function localTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

export function defaultCadence(): Cadence {
  return { cadence: 'weekly', hour: 9, minute: 0, weekday: 0, timezone: localTimezone() };
}

function ordinal(n: number): string {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

/** "Weekly on Monday at 09:00", plus the zone when it is not the reader's. */
export function describeCadence(c: Cadence | null, readerZone = localTimezone()): string {
  if (!c) return 'No schedule';
  const time = `${String(c.hour).padStart(2, '0')}:${String(c.minute ?? 0).padStart(2, '0')}`;
  const zone = c.timezone && c.timezone !== readerZone ? ` (${c.timezone})` : '';
  if (c.cadence === 'daily') return `Daily at ${time}${zone}`;
  if (c.cadence === 'weekly') return `Weekly on ${WEEKDAYS[c.weekday ?? 0]} at ${time}${zone}`;
  return `Monthly on the ${ordinal(c.day_of_month ?? 1)} at ${time}${zone}`;
}

/** The API's naive-UTC timestamps, read as UTC. */
export function parseUtc(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}
