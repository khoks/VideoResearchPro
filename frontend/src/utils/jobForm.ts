/*
 * The submit form's state and its conversions, kept pure so they can be
 * tested (S-8.6.1). Three ways into the form — a saved draft, "Duplicate" of
 * a run, a template — and one way out (a `JobCreate`). The Duplicate path
 * once hard-coded `outputLength: 'auto'` and had no visual-analysis field,
 * so a duplicated deep, visual run came back shallow and blind (T-8.6.1.0).
 */
import type { Job, JobCreate, JobType, OutputLength } from '../types/job';
import type { TemplateParameters } from '../services/jobTemplatesApi';

export const CHANNEL_TYPE_OPTIONS = [
  'educational',
  'academic',
  'news',
  'entertainment',
  'podcast',
  'tutorial',
] as const;

export type ChannelTypeOption = (typeof CHANNEL_TYPE_OPTIONS)[number];

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

function outputLengthOf(value: string | null | undefined): OutputLength {
  return value && (OUTPUT_LENGTHS as readonly string[]).includes(value)
    ? (value as OutputLength)
    : 'auto';
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
    };
  } catch {
    return DEFAULT_FORM;
  }
}

/** A channel or subscription recipe that leaves the channels to each run. */
export function templateNeedsChannels(params: TemplateParameters): boolean {
  return params.job_type !== 'topic' && !(params.channel_list && params.channel_list.length > 0);
}

/** "Duplicate": every parameter of the run, including depth and the visual flag. */
export function jobToFormState(job: Job): JobFormState {
  return {
    jobType: job.job_type,
    topic: job.topic ?? '',
    searchInstructions: job.search_instructions ?? '',
    numVideos: job.num_videos ?? 10,
    outputLength: outputLengthOf(job.output_length),
    visualAnalysis: job.visual_analysis === true,
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
  if (form.visualAnalysis) data.visual_analysis = true;

  if (form.jobType === 'topic') {
    if (requireTopic && !form.topic.trim()) return { ok: false, error: 'Topic is required.' };
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
      visual_analysis: rest.visual_analysis ?? false,
      channel_list: rest.channel_list ?? null,
      videos_per_channel: rest.job_type === 'channel' ? rest.videos_per_channel ?? 10 : null,
    },
  };
}
