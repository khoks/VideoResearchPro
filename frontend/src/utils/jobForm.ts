/*
 * The submit form's state and its conversions, kept pure so they can be
 * tested (S-8.6.1). Three ways into the form — a saved draft, "Duplicate" of
 * a run, a template — and one way out (a `JobCreate`). The Duplicate path
 * once hard-coded `outputLength: 'auto'` and had no visual-analysis field,
 * so a duplicated deep, visual run came back shallow and blind (T-8.6.1.0).
 */
import { featureFlags } from '../config/features';
import type { Job, JobCreate, JobType, OutputLength } from '../types/job';
import type { TemplateParameters } from '../services/jobTemplatesApi';
import type { SourceHold } from '../stores/systemStatusStore';

export const CHANNEL_TYPE_OPTIONS = [
  'educational',
  'academic',
  'news',
  'entertainment',
  'podcast',
  'tutorial',
] as const;

export type ChannelTypeOption = (typeof CHANNEL_TYPE_OPTIONS)[number];

/**
 * S-1.5.13: what a topic run can search, in the server's canonical order
 * (`backend/app/services/job_source_types.py`, SEARCHABLE_SOURCE_TYPES).
 * `capability` names the `/health` flag that says whether this install can
 * search a type. A credential-gated type is offered only when the flag is
 * true, and the server refuses it with a 422 otherwise. Tweet search is the
 * BYOK case (T-1.5.9.3). A `keyless` type needs no credential, so it is on
 * offer until the flag says false: a blank base URL (T-1.5.13.6), or a source
 * on hold for refusing this install (T-1.5.14.1).
 */
export const SOURCE_TYPE_OPTIONS = [
  { value: 'video', label: 'YouTube' },
  { value: 'reddit_post', label: 'Reddit', capability: 'reddit_search_enabled' },
  { value: 'hn_story', label: 'Hacker News', capability: 'hn_search_enabled', keyless: true },
  { value: 'mastodon_post', label: 'Mastodon', capability: 'mastodon_search_enabled', keyless: true },
  { value: 'bluesky_post', label: 'Bluesky', capability: 'bluesky_search_enabled', keyless: true },
  { value: 'podcast_episode', label: 'Podcasts', capability: 'podcast_search_enabled', keyless: true },
  { value: 'article', label: 'Web articles', capability: 'article_search_enabled' },
  { value: 'tweet', label: 'X / Twitter', capability: 'twitter_search_enabled' },
] as const satisfies readonly { value: string; label: string; capability?: string; keyless?: boolean }[];

/** S-8.6.3: mirrors MAX_PUBLISHED_AFTER_DAYS in `backend/app/schemas/job.py`. */
export const MAX_PUBLISHED_AFTER_DAYS = 3650;

export type SourceType = (typeof SOURCE_TYPE_OPTIONS)[number]['value'];
export type SourceTypeOption = (typeof SOURCE_TYPE_OPTIONS)[number];

export const DEFAULT_SOURCE_TYPES: readonly SourceType[] = ['video'];

const SOURCE_TYPE_ORDER: readonly SourceType[] = SOURCE_TYPE_OPTIONS.map((o) => o.value);

/** Known types only, de-duplicated, in canonical order (may be empty). */
function canonicalSourceTypes(list: readonly string[]): SourceType[] {
  return SOURCE_TYPE_ORDER.filter((v) => list.includes(v));
}

/** A stored or received list as form state: YouTube alone when nothing usable is left. */
function sourceTypesOf(list: readonly string[] | null | undefined): SourceType[] {
  const known = canonicalSourceTypes(list ?? []);
  return known.length > 0 ? known : [...DEFAULT_SOURCE_TYPES];
}

export function isDefaultSourceTypes(list: readonly string[]): boolean {
  return list.length === DEFAULT_SOURCE_TYPES.length && DEFAULT_SOURCE_TYPES.every((v) => list.includes(v));
}

export function sourceTypeLabel(value: string): string {
  return SOURCE_TYPE_OPTIONS.find((o) => o.value === value)?.label ?? value.replace(/_/g, ' ');
}

/**
 * The options this install can search, from `/health` capabilities. Until
 * the first poll answers (null) the types that need no credential are offered.
 */
export function offeredSourceTypes(capabilities: Record<string, boolean> | null): SourceTypeOption[] {
  return SOURCE_TYPE_OPTIONS.filter((o) => {
    if (!('capability' in o)) return true;
    const flag = capabilities?.[o.capability];
    return 'keyless' in o ? flag !== false : flag === true;
  });
}

/**
 * Why a source is not on offer although it is set up: it refused this install
 * (T-1.5.14.1). Null when nothing is on hold. Says when it will be tried again
 * only in words, because `until` moves if a run refuses it again.
 */
export function heldSourcesNote(holds: Record<string, SourceHold>): string | null {
  const held = Object.keys(holds);
  if (held.length === 0) return null;
  const one = held.length === 1;
  return `${held.map((v) => sourceTypeLabel(v)).join(', ')} refused ${
    one ? 'its' : 'their'
  } last search from this install, so ${one ? 'it is' : 'they are'} not offered for now.`;
}

/**
 * Selected types the install cannot search (a run or template saved while a
 * source was set up). Empty until capabilities are known, so a slow first
 * poll never flags anything.
 */
export function unavailableSourceTypes(
  selected: readonly string[],
  capabilities: Record<string, boolean> | null,
): SourceType[] {
  if (capabilities === null) return [];
  const offered: readonly string[] = offeredSourceTypes(capabilities).map((o) => o.value);
  return canonicalSourceTypes(selected).filter((v) => !offered.includes(v));
}

/**
 * How a run shares its `num_videos` across the sources it searches, mirroring
 * the server's `job_source_types.share_limits`: as even as it can be, the
 * remainder to the earlier sources in canonical order. `num_videos` is the
 * run's whole budget (the plan cap is checked against it), never a per-source
 * figure.
 */
export function sourceTypeShares(total: number, sourceTypes: readonly SourceType[]): Record<string, number> {
  const types = canonicalSourceTypes(sourceTypes);
  if (types.length === 0) return {};
  const budget = Math.max(0, Math.floor(total));
  const base = Math.floor(budget / types.length);
  const remainder = budget % types.length;
  return Object.fromEntries(types.map((v, i) => [v, base + (i < remainder ? 1 : 0)]));
}

/** Toggle one type, keeping canonical order. The result may be empty. */
export function toggleSourceType(selected: readonly SourceType[], value: SourceType): SourceType[] {
  return selected.includes(value)
    ? selected.filter((v) => v !== value)
    : canonicalSourceTypes([...selected, value]);
}

export interface JobFormState {
  jobType: JobType;
  topic: string;
  searchInstructions: string;
  numVideos: number;
  minDuration: string;
  maxDuration: string;
  channelFilters: ChannelTypeOption[];
  preferredChannels: string;
  channelList: string;
  videosPerChannel: number;
  subscriptionChannels: string;
  outputLength: OutputLength;
  /**
   * Carried from a duplicated run or a template, never offered as a fresh
   * opt-in: the job-creation toggle is S-1.18.2, deferred by D-071 / D-075.
   */
  visualAnalysis: boolean;
  /** S-1.5.13: what a topic run searches; `['video']` is the default. */
  sourceTypes: SourceType[];
  /**
   * S-8.6.3: prefer sources from the last N days, as typed; empty is no
   * preference. A ranking preference, never a filter, and only YouTube
   * results are ranked, so it needs YouTube among `sourceTypes`.
   */
  publishedAfterDays: string;
}

export const DEFAULT_FORM: JobFormState = {
  jobType: 'topic',
  topic: '',
  searchInstructions: '',
  numVideos: 10,
  outputLength: 'auto',
  minDuration: '',
  maxDuration: '',
  channelFilters: [],
  preferredChannels: '',
  channelList: '',
  videosPerChannel: 10,
  subscriptionChannels: '',
  visualAnalysis: false,
  sourceTypes: [...DEFAULT_SOURCE_TYPES],
  publishedAfterDays: '',
};

const OUTPUT_LENGTHS: readonly OutputLength[] = ['auto', 'brief', 'standard', 'deep'];

function validFilters(list: readonly string[] | null | undefined): ChannelTypeOption[] {
  return (list ?? []).filter((c): c is ChannelTypeOption =>
    (CHANNEL_TYPE_OPTIONS as readonly string[]).includes(c),
  );
}

function lines(list: readonly string[] | null | undefined): string {
  return list && list.length > 0 ? list.join('\n') : '';
}

/** "30 days", or "day" for one, to follow "the last" (S-8.6.3). */
export function windowLabel(days: number): string {
  return days === 1 ? 'day' : `${days} days`;
}

function windowOf(days: number | null | undefined): string {
  return days != null ? String(days) : '';
}

function outputLengthOf(value: string | null | undefined): OutputLength {
  return value && (OUTPUT_LENGTHS as readonly string[]).includes(value)
    ? (value as OutputLength)
    : 'auto';
}

/**
 * Whether the form holds anything of the reader's. The research type alone
 * does not count: it is only the tab they are on.
 */
export function isDraftForm(form: JobFormState): boolean {
  return (Object.keys(DEFAULT_FORM) as (keyof JobFormState)[]).some(
    (key) => key !== 'jobType' && JSON.stringify(form[key]) !== JSON.stringify(DEFAULT_FORM[key]),
  );
}

/** Restore a saved draft, tolerating fields from older versions. */
export function parseDraft(raw: string | null): JobFormState {
  if (!raw) return DEFAULT_FORM;
  try {
    const parsed = JSON.parse(raw) as Partial<JobFormState>;
    return {
      ...DEFAULT_FORM,
      ...parsed,
      outputLength: outputLengthOf(parsed.outputLength),
      visualAnalysis: parsed.visualAnalysis === true,
      channelFilters: Array.isArray(parsed.channelFilters) ? validFilters(parsed.channelFilters) : [],
      sourceTypes: sourceTypesOf(Array.isArray(parsed.sourceTypes) ? parsed.sourceTypes : null),
      publishedAfterDays: typeof parsed.publishedAfterDays === 'string' ? parsed.publishedAfterDays : '',
    };
  } catch {
    return DEFAULT_FORM;
  }
}

/** A channel or subscription recipe that leaves the channels to each run. */
export function templateNeedsChannels(params: TemplateParameters): boolean {
  return params.job_type !== 'topic' && !(params.channel_list && params.channel_list.length > 0);
}

/** "Duplicate": every parameter of the run, including depth, the visual flag and its sources. */
export function jobToFormState(job: Job): JobFormState {
  return {
    jobType: job.job_type,
    topic: job.topic ?? '',
    searchInstructions: job.search_instructions ?? '',
    numVideos: job.num_videos ?? 10,
    outputLength: outputLengthOf(job.output_length),
    visualAnalysis: job.visual_analysis === true,
    sourceTypes: job.job_type === 'topic' ? sourceTypesOf(job.source_types) : [...DEFAULT_SOURCE_TYPES],
    publishedAfterDays: job.job_type === 'topic' ? windowOf(job.published_after_days) : '',
    minDuration: job.min_duration_minutes != null ? String(job.min_duration_minutes) : '',
    maxDuration: job.max_duration_minutes != null ? String(job.max_duration_minutes) : '',
    channelFilters: validFilters(job.channel_type_filters),
    preferredChannels: lines(job.preferred_channels),
    channelList: job.job_type === 'channel' ? lines(job.channel_list) : '',
    videosPerChannel: job.videos_per_channel ?? 10,
    subscriptionChannels: job.job_type === 'subscription' ? lines(job.channel_list) : '',
  };
}

/**
 * A template fills every frozen field; the topic is the reader's to type
 * (kept from the form if they already typed one). `{{topic}}` stays in the
 * instructions — the server fills it at submission.
 */
export function templateToFormState(params: TemplateParameters, keepTopic = ''): JobFormState {
  return {
    jobType: params.job_type,
    topic: params.job_type === 'topic' ? keepTopic : '',
    searchInstructions: params.search_instructions ?? '',
    numVideos: params.num_videos ?? 10,
    outputLength: outputLengthOf(params.output_length),
    visualAnalysis: params.visual_analysis === true,
    sourceTypes: params.job_type === 'topic' ? sourceTypesOf(params.source_types) : [...DEFAULT_SOURCE_TYPES],
    publishedAfterDays: params.job_type === 'topic' ? windowOf(params.published_after_days) : '',
    minDuration: params.min_duration_minutes != null ? String(params.min_duration_minutes) : '',
    maxDuration: params.max_duration_minutes != null ? String(params.max_duration_minutes) : '',
    channelFilters: validFilters(params.channel_type_filters),
    preferredChannels: lines(params.preferred_channels),
    channelList: params.job_type === 'channel' ? lines(params.channel_list) : '',
    videosPerChannel: params.videos_per_channel ?? 10,
    subscriptionChannels: params.job_type === 'subscription' ? lines(params.channel_list) : '',
  };
}

const CHANNEL_URL_RE =
  /^(?:@[\w.-]{1,}|UC[\w-]{22}|(?:https?:\/\/)?(?:www\.)?youtube\.com\/(?:@[\w.-]{1,}|channel\/[\w-]{1,}|c\/[\w.-]{1,}|user\/[\w.-]{1,})\/?)$/i;

export function parseChannelList(raw: string): string[] {
  return raw
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);
}

export function validateChannels(entries: string[]): string[] {
  return entries.filter((line) => !CHANNEL_URL_RE.test(line));
}

function truncatedList(items: string[]): string {
  return `${items.slice(0, 3).join(', ')}${items.length > 3 ? '…' : ''}`;
}

export type FormResult = { ok: true; data: JobCreate } | { ok: false; error: string };

/**
 * The form as a `JobCreate`, or the first problem a reader must fix.
 * `requireTopic` / `requireChannels: false` build a template's parameters,
 * which may leave the topic (always) and the channels (S-8.6.2) to each run.
 */
export function formToJobCreate(
  form: JobFormState,
  { requireTopic = true, requireChannels = true } = {},
): FormResult {
  const data: JobCreate = { job_type: form.jobType };
  if (form.outputLength !== 'auto') data.output_length = form.outputLength;
  // D-105: while the option is hidden a carried-over flag never starts a run.
  if (form.visualAnalysis && featureFlags.visualAnalysis) data.visual_analysis = true;

  if (form.jobType === 'topic') {
    if (requireTopic && !form.topic.trim()) return { ok: false, error: 'Topic is required.' };
    const sources = canonicalSourceTypes(form.sourceTypes);
    if (sources.length === 0) return { ok: false, error: 'Choose at least one source to search.' };
    if (form.numVideos < sources.length) {
      return {
        ok: false,
        error: `Ask for at least ${sources.length} results, one per source: the number is shared across the sources you search.`,
      };
    }
    // S-1.5.13: YouTube alone is the server's default, so it is left out and
    // the request is the one every run sent before the choice existed.
    if (!isDefaultSourceTypes(sources)) data.source_types = sources;
    // S-8.6.3: only YouTube results are ranked, so without YouTube there is
    // nothing for the window to steer and the server would refuse it. The
    // form hides the control then, and the typed value waits in the state.
    if (form.publishedAfterDays.trim() && sources.includes('video')) {
      const days = Number(form.publishedAfterDays);
      if (!Number.isInteger(days) || days < 1 || days > MAX_PUBLISHED_AFTER_DAYS) {
        return {
          ok: false,
          error: `Enter a whole number of days from 1 to ${MAX_PUBLISHED_AFTER_DAYS} for the publish window, or leave it empty.`,
        };
      }
      data.published_after_days = days;
    }
    if (form.topic.trim()) data.topic = form.topic.trim();
    data.num_videos = form.numVideos;
    data.search_instructions = form.searchInstructions || undefined;
    if (form.minDuration) data.min_duration_minutes = parseInt(form.minDuration, 10);
    if (form.maxDuration) data.max_duration_minutes = parseInt(form.maxDuration, 10);
    if (form.channelFilters.length > 0) data.channel_type_filters = [...form.channelFilters];
    const preferred = parseChannelList(form.preferredChannels);
    if (preferred.length > 0) {
      const invalid = validateChannels(preferred);
      if (invalid.length > 0) {
        return { ok: false, error: `Invalid preferred-channel entries: ${truncatedList(invalid)}` };
      }
      data.preferred_channels = preferred;
    }
    return { ok: true, data };
  }

  const raw = form.jobType === 'channel' ? form.channelList : form.subscriptionChannels;
  const entries = parseChannelList(raw);
  if (entries.length === 0 && requireChannels) {
    return { ok: false, error: 'Provide at least one channel URL, handle, or UC-ID.' };
  }
  const invalid = validateChannels(entries);
  if (invalid.length > 0) return { ok: false, error: `Invalid channel entries: ${truncatedList(invalid)}` };
  if (entries.length > 0) data.channel_list = entries;
  if (form.jobType === 'channel') {
    data.videos_per_channel = form.videosPerChannel;
    data.num_videos = form.numVideos;
    if (form.minDuration) data.min_duration_minutes = parseInt(form.minDuration, 10);
    if (form.maxDuration) data.max_duration_minutes = parseInt(form.maxDuration, 10);
  }
  return { ok: true, data };
}

/** The form's frozen half, as a template version stores it. */
export function formToTemplateParameters(form: JobFormState): { ok: true; params: TemplateParameters } | { ok: false; error: string } {
  const result = formToJobCreate(form, { requireTopic: false, requireChannels: false });
  if (!result.ok) return result;
  const { topic: _topic, ...rest } = result.data;
  void _topic;
  return {
    ok: true,
    params: {
      job_type: rest.job_type,
      search_instructions: rest.search_instructions ?? null,
      num_videos: rest.num_videos ?? 10,
      min_duration_minutes: rest.min_duration_minutes ?? null,
      max_duration_minutes: rest.max_duration_minutes ?? null,
      channel_type_filters: rest.channel_type_filters ?? null,
      preferred_channels: rest.preferred_channels ?? null,
      output_length: rest.output_length ?? null,
      // The form's own value, not the run payload: a template keeps its
      // stored setting while D-105 hides the option, so it returns intact.
      visual_analysis: form.visualAnalysis,
      source_types: rest.source_types ?? null,
      published_after_days: rest.published_after_days ?? null,
      channel_list: rest.channel_list ?? null,
      videos_per_channel: rest.job_type === 'channel' ? rest.videos_per_channel ?? 10 : null,
    },
  };
}
