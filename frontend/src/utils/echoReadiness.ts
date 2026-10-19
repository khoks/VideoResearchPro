/*
 * Pure logic for the Echo page: readiness arithmetic, the closed set of
 * context kinds, grouping, and expiry. No React.
 *
 * Kinds mirror `backend/app/services/echo_service.py::SUPPORTED_KINDS`;
 * the backend rejects anything else with 400, so keep the two in sync.
 */

import type { EchoStatus, PersonalContextItem } from '../services/echoApi';

export interface KindMeta {
  kind: string;
  label: string;
  /** What belongs here, in the second person. */
  hint: string;
  /** Example key, shown as the placeholder. */
  exampleKey: string;
}

export const ECHO_KINDS: ReadonlyArray<KindMeta> = [
  { kind: 'location', label: 'Location', hint: 'Where you live and where you are based.', exampleKey: 'home city' },
  { kind: 'interest', label: 'Interests', hint: 'Topics you follow and read about.', exampleKey: 'Indian macroeconomics' },
  { kind: 'hobby', label: 'Hobbies', hint: 'What you do for its own sake.', exampleKey: 'trail running' },
  { kind: 'work', label: 'Work', hint: 'Role, employer, field, projects.', exampleKey: 'current role' },
  { kind: 'talent', label: 'Talents', hint: 'Things that come naturally to you.', exampleKey: 'explaining systems' },
  { kind: 'skill', label: 'Skills', hint: 'Things you trained yourself to do.', exampleKey: 'Python' },
  { kind: 'personality_trait', label: 'Personality traits', hint: 'How you tend to think and react. At least one is required before Echo is ready.', exampleKey: 'contrarian' },
  { kind: 'life_event', label: 'Life events', hint: 'Moves, milestones, turning points.', exampleKey: 'moved to Pune 2024' },
  { kind: 'daily_routine', label: 'Daily routines', hint: 'The shape of an ordinary day.', exampleKey: 'morning reading' },
  { kind: 'place', label: 'Places', hint: 'Places that matter to you beyond where you live.', exampleKey: 'grandparents’ village' },
];

const KIND_INDEX = new Map(ECHO_KINDS.map((k, i) => [k.kind, i]));

export function kindLabel(kind: string): string {
  return ECHO_KINDS.find((k) => k.kind === kind)?.label ?? kind.replace(/_/g, ' ');
}

export function kindMetaFor(kind: string): KindMeta {
  return (
    ECHO_KINDS.find((k) => k.kind === kind) ?? {
      kind,
      label: kind.replace(/_/g, ' '),
      hint: '',
      exampleKey: '',
    }
  );
}

// ---------------------------------------------------------------------------
// Readiness
// ---------------------------------------------------------------------------

export type ReadinessGate = 'rows' | 'sources' | 'personality';

export interface ReadinessPart {
  gate: ReadinessGate;
  label: string;
  current: number;
  target: number;
  /** 0..1, capped. */
  fraction: number;
  met: boolean;
  /** Honest one-liner about what moves this gate. */
  hint: string;
}

export interface Readiness {
  ready: boolean;
  /** 0..100. 100 when the backend says ready, else the mean of the gates. */
  percent: number;
  parts: ReadinessPart[];
}

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(1, n));
}

/**
 * Three gates, equally weighted, because the backend treats them as three
 * independent AND conditions. `connectorsAvailable` controls the honesty
 * line on the sources gate: with an empty connector registry the only
 * source a user can produce is `manual`, so the gate cannot be met yet.
 */
export function computeReadiness(status: EchoStatus, connectorsAvailable: number): Readiness {
  const rowsFraction = status.threshold_total > 0 ? clamp01(status.total_rows / status.threshold_total) : 1;
  const sourcesFraction =
    status.threshold_sources > 0 ? clamp01(status.distinct_sources / status.threshold_sources) : 1;
  const personalityFraction = status.has_personality_trait ? 1 : 0;

  const parts: ReadinessPart[] = [
    {
      gate: 'rows',
      label: 'Facts recorded',
      current: status.total_rows,
      target: status.threshold_total,
      fraction: rowsFraction,
      met: status.total_rows >= status.threshold_total,
      hint: 'Every entry you add counts, whatever its kind.',
    },
    {
      gate: 'sources',
      label: 'Distinct sources',
      current: status.distinct_sources,
      target: status.threshold_sources,
      fraction: sourcesFraction,
      met: status.distinct_sources >= status.threshold_sources,
      hint:
        connectorsAvailable > 0
          ? 'Manual entries are one source; each connected service adds another.'
          : 'Manual entries are one source. Connectors have not shipped, so this gate cannot be met yet.',
    },
    {
      gate: 'personality',
      label: 'Personality trait',
      current: status.has_personality_trait ? 1 : 0,
      target: 1,
      fraction: personalityFraction,
      met: status.has_personality_trait,
      hint: 'Add at least one entry under Personality traits.',
    },
  ];

  const mean = (rowsFraction + sourcesFraction + personalityFraction) / 3;
  const percent = status.ready ? 100 : Math.min(99, Math.round(mean * 100));
  return { ready: status.ready, percent, parts };
}

// ---------------------------------------------------------------------------
// Grouping & expiry
// ---------------------------------------------------------------------------

export interface KindGroup {
  meta: KindMeta;
  rows: PersonalContextItem[];
}

/**
 * Group rows by kind in canonical order. Every known kind appears, empty
 * or not, so the page shows the whole shape of what Echo can hold; unknown
 * kinds (if the backend ever grows one) are appended at the end.
 */
export function groupContextByKind(rows: PersonalContextItem[]): KindGroup[] {
  const groups = new Map<string, PersonalContextItem[]>();
  for (const k of ECHO_KINDS) groups.set(k.kind, []);
  for (const r of rows) {
    if (!groups.has(r.kind)) groups.set(r.kind, []);
    groups.get(r.kind)!.push(r);
  }
  const ordered = [...groups.keys()].sort((a, b) => {
    const ia = KIND_INDEX.get(a) ?? Number.MAX_SAFE_INTEGER;
    const ib = KIND_INDEX.get(b) ?? Number.MAX_SAFE_INTEGER;
    return ia - ib || a.localeCompare(b);
  });
  return ordered.map((kind) => ({
    meta: kindMetaFor(kind),
    rows: [...groups.get(kind)!].sort((a, b) => a.key.localeCompare(b.key)),
  }));
}

export interface SourceCount {
  source: string;
  count: number;
}

export function countBySource(rows: PersonalContextItem[]): SourceCount[] {
  const counts = new Map<string, number>();
  for (const r of rows) counts.set(r.source, (counts.get(r.source) ?? 0) + 1);
  return [...counts.entries()]
    .map(([source, count]) => ({ source, count }))
    .sort((a, b) => b.count - a.count || a.source.localeCompare(b.source));
}

export function isExpired(row: Pick<PersonalContextItem, 'expires_at'>, now: Date = new Date()): boolean {
  if (!row.expires_at) return false;
  const t = new Date(row.expires_at).getTime();
  return Number.isFinite(t) && t <= now.getTime();
}

export function formatConfidence(confidence: number): string {
  return `${Math.round(clamp01(confidence) * 100)}%`;
}

/** Keys travel in the URL path on delete; a slash would never route. */
export function validateContextKey(key: string): string | null {
  const k = key.trim();
  if (!k) return 'Give this entry a short label.';
  if (k.length > 128) return 'Keep the label under 128 characters.';
  if (k.includes('/')) return 'Labels cannot contain a slash.';
  return null;
}

/** `<input type="date">` value → ISO instant at the end of that UTC day, or null. */
export function dateInputToExpiresAt(value: string): string | null {
  if (!value) return null;
  const d = new Date(`${value}T23:59:59Z`);
  return Number.isFinite(d.getTime()) ? d.toISOString() : null;
}

export function expiresAtToDateInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return '';
  return d.toISOString().slice(0, 10);
}
