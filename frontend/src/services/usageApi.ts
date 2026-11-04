import api from './api';

/** `GET /usage` (E-5.2): the signed-in user's own usage, recorded and never limited. */
export interface UsageAmounts {
  llm_tokens_in: number;
  llm_tokens_out: number;
  llm_calls: number;
  youtube_units: number;
}

export interface UsageFeatureRow {
  feature: string;
  label: string;
  today: UsageAmounts;
  last_30_days: UsageAmounts;
}

export interface UsageSummary {
  /** UTC day, YYYY-MM-DD. */
  today: string;
  window_start: string;
  window_days: number;
  /** First day anything was recorded for this account; null before then. */
  metered_since: string | null;
  features: UsageFeatureRow[];
  totals: { today: UsageAmounts; last_30_days: UsageAmounts };
}

export const usageApi = {
  get: () => api.get<UsageSummary>('/usage').then((r) => r.data),
};

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });

/** 950 → "950", 12_345 → "12.3K", 1_200_000 → "1.2M". */
export function formatCount(n: number): string {
  return n < 1000 ? String(n) : compact.format(n);
}

/** The lines a usage cell shows; empty when nothing was used. */
export function usageLines(a: UsageAmounts): string[] {
  const lines: string[] = [];
  if (a.llm_tokens_in || a.llm_tokens_out) {
    lines.push(`${formatCount(a.llm_tokens_in)} in · ${formatCount(a.llm_tokens_out)} out`);
  }
  if (a.llm_calls) lines.push(`${formatCount(a.llm_calls)} model call${a.llm_calls === 1 ? '' : 's'}`);
  if (a.youtube_units) lines.push(`${formatCount(a.youtube_units)} YouTube unit${a.youtube_units === 1 ? '' : 's'}`);
  return lines;
}
