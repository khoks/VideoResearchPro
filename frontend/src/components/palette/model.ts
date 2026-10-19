/**
 * Pure parts of the command palette (S-8.2.2): action filtering, recent
 * items, group labels. Kept out of the component so they test without a DOM.
 */
import type { SearchType } from '../../services/searchApi';

export interface PaletteAction {
  id: string;
  label: string;
  /** Extra words the filter matches ("theme" finds "Switch to dark mode"). */
  keywords?: string;
  hint?: string;
  run: () => void;
}

/** Every word of the query appears somewhere in the label or keywords. */
export function matchesQuery(action: Pick<PaletteAction, 'label' | 'keywords'>, query: string): boolean {
  const hay = `${action.label} ${action.keywords ?? ''}`.toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((w) => hay.includes(w));
}

export const GROUP_LABEL: Record<SearchType, string> = {
  jobs: 'Runs',
  documents: 'Sources',
  channels: 'Channels',
  qa: 'Questions',
  knowledge: 'Knowledge reports',
};

export interface RecentItem {
  href: string;
  title: string;
  subtitle: string;
  kind: string;
}

const RECENT_KEY = 'pratidhvani:palette-recent';
const RECENT_MAX = 6;

export function loadRecent(): RecentItem[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed)
      ? parsed.filter((r): r is RecentItem => !!r && typeof r === 'object' && typeof (r as RecentItem).href === 'string').slice(0, RECENT_MAX)
      : [];
  } catch {
    return [];
  }
}

/** Newest first, one entry per href, capped. Returns the new list. */
export function pushRecent(item: RecentItem, current = loadRecent()): RecentItem[] {
  const next = [item, ...current.filter((r) => r.href !== item.href)].slice(0, RECENT_MAX);
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable */
  }
  return next;
}

export function countResults(groups: { items: unknown[] }[], actions: number): number {
  return groups.reduce((n, g) => n + g.items.length, 0) + actions;
}
