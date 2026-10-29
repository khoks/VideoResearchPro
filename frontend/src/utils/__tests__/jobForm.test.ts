import { afterEach, describe, expect, it } from 'vitest';
import { featureFlags } from '../../config/features';

// The flag is module state shared by every test in this file; start each hidden.
afterEach(() => {
  featureFlags.visualAnalysis = false;
});
import {
  DEFAULT_FORM,
  formToJobCreate,
  formToTemplateParameters,
  jobToFormState,
  offeredSourceTypes,
  parseDraft,
  sourceTypeShares,
  templateNeedsChannels,
  templateToFormState,
  toggleSourceType,
  unavailableSourceTypes,
} from '../jobForm';
import type { Job } from '../../types/job';
import type { TemplateParameters } from '../../services/jobTemplatesApi';

const DEEP_VISUAL_JOB: Job = {
  id: 'job-1',
  job_type: 'topic',
  status: 'completed',
  created_at: '2026-10-19T00:00:00Z',
  updated_at: '2026-10-19T00:00:00Z',
  completed_at: null,
  topic: 'tariffs',
  search_instructions: 'Prefer economists.',
  num_videos: 25,
  min_duration_minutes: 10,
  max_duration_minutes: null,
  channel_type_filters: ['educational', 'not-a-real-filter'],
  preferred_channels: ['@lexfridman'],
  channel_list: null,
  videos_per_channel: null,
  output_length: 'deep',
  visual_analysis: true,
  template_id: null,
  template_version: null,
  progress_pct: 100,
  progress_message: null,
  error_message: null,
  video_count: 25,
  transcript_count: 25,
  has_report: true,
};

describe('Duplicate (T-8.6.1.0)', () => {
  it('carries report depth and the visual flag instead of resetting them', () => {
    const form = jobToFormState(DEEP_VISUAL_JOB);
    expect(form.outputLength).toBe('deep');
    expect(form.visualAnalysis).toBe(true);
  });

  it('round-trips a run into the same JobCreate', () => {
    featureFlags.visualAnalysis = true;   // the option shown (before or after D-105)
    const result = formToJobCreate(jobToFormState(DEEP_VISUAL_JOB));
    expect(result).toEqual({
      ok: true,
      data: {
        job_type: 'topic',
        topic: 'tariffs',
        search_instructions: 'Prefer economists.',
        num_videos: 25,
        min_duration_minutes: 10,
        channel_type_filters: ['educational'],
        preferred_channels: ['@lexfridman'],
        output_length: 'deep',
        visual_analysis: true,
      },
    });
  });

  it('treats an unknown or missing depth as auto and omits it', () => {
    const form = jobToFormState({ ...DEEP_VISUAL_JOB, output_length: null, visual_analysis: false });
    expect(form.outputLength).toBe('auto');
    const result = formToJobCreate(form);
    expect(result.ok && 'output_length' in result.data).toBe(false);
    expect(result.ok && 'visual_analysis' in result.data).toBe(false);
  });
});

describe('templates (S-8.6.1)', () => {
  const params: TemplateParameters = {
    job_type: 'topic',
    search_instructions: 'Interviews about {{topic}}',
    num_videos: 30,
    min_duration_minutes: null,
    max_duration_minutes: 90,
    channel_type_filters: ['news'],
    preferred_channels: null,
    output_length: 'brief',
    visual_analysis: false,
    source_types: ['video', 'hn_story'],
    channel_list: null,
    videos_per_channel: null,
  };

  it('fills every frozen field and keeps the topic the reader typed', () => {
    const form = templateToFormState(params, 'rare earths');
    expect(form.topic).toBe('rare earths');
    expect(form.searchInstructions).toBe('Interviews about {{topic}}');
    expect(form.outputLength).toBe('brief');
    expect(form.maxDuration).toBe('90');
    expect(form.channelFilters).toEqual(['news']);
    expect(form.sourceTypes).toEqual(['video', 'hn_story']);
  });

  it('turns the form back into the same parameters (no topic)', () => {
    const result = formToTemplateParameters(templateToFormState(params, 'anything'));
    expect(result).toEqual({ ok: true, params });
  });

  it('lets a channel recipe leave the channels to each run (S-8.6.2)', () => {
    const result = formToTemplateParameters({ ...DEFAULT_FORM, jobType: 'channel' });
    expect(result.ok && result.params.channel_list).toBe(null);
    expect(result.ok && templateNeedsChannels(result.params)).toBe(true);
  });

  it('still requires channels to submit a channel run', () => {
    const result = formToJobCreate({ ...DEFAULT_FORM, jobType: 'channel' });
    expect(result.ok).toBe(false);
  });
});

describe('source types (S-1.5.13)', () => {
  const MIXED_JOB: Job = { ...DEEP_VISUAL_JOB, source_types: ['video', 'reddit_post'] };

  it('Duplicate carries the run\'s sources into the request', () => {
    const form = jobToFormState(MIXED_JOB);
    expect(form.sourceTypes).toEqual(['video', 'reddit_post']);
    const result = formToJobCreate(form);
    expect(result.ok && result.data.source_types).toEqual(['video', 'reddit_post']);
  });

  it('leaves YouTube alone out of the request, so a default run is unchanged', () => {
    const result = formToJobCreate({ ...DEFAULT_FORM, topic: 'x' });
    expect(result).toEqual({ ok: true, data: { job_type: 'topic', topic: 'x', num_videos: 10 } });
    // A run from before the field (no source_types in the response) duplicates as YouTube only.
    const { source_types: _omit, ...older } = MIXED_JOB;
    void _omit;
    expect(jobToFormState(older).sourceTypes).toEqual(['video']);
  });

  it('sends a non-YouTube-only choice in canonical order', () => {
    const form = { ...DEFAULT_FORM, topic: 'x', sourceTypes: toggleSourceType(toggleSourceType(['video'], 'tweet'), 'video') };
    expect(form.sourceTypes).toEqual(['tweet']);
    const both = toggleSourceType(['tweet'], 'hn_story');
    expect(both).toEqual(['hn_story', 'tweet']);
    const result = formToJobCreate({ ...form, sourceTypes: both });
    expect(result.ok && result.data.source_types).toEqual(['hn_story', 'tweet']);
  });

  it('refuses an empty choice', () => {
    const result = formToJobCreate({ ...DEFAULT_FORM, topic: 'x', sourceTypes: [] });
    expect(result).toEqual({ ok: false, error: 'Choose at least one source to search.' });
  });

  it('shares the results of a run across its sources, as the server does', () => {
    // num_videos is the whole run's budget (the plan cap bounds it), so five
    // sources never collect five times the cap.
    expect(sourceTypeShares(100, ['video', 'reddit_post', 'hn_story', 'mastodon_post', 'bluesky_post'])).toEqual({
      video: 20,
      reddit_post: 20,
      hn_story: 20,
      mastodon_post: 20,
      bluesky_post: 20,
    });
    // The remainder goes to the earlier sources in canonical order.
    expect(sourceTypeShares(5, ['hn_story', 'video', 'reddit_post'])).toEqual({ video: 2, reddit_post: 2, hn_story: 1 });
    expect(sourceTypeShares(10, ['video'])).toEqual({ video: 10 });
  });

  it('refuses fewer results than sources', () => {
    const result = formToJobCreate({ ...DEFAULT_FORM, topic: 'x', numVideos: 2, sourceTypes: ['video', 'hn_story', 'podcast_episode'] });
    expect(result.ok).toBe(false);
    expect(!result.ok && result.error).toContain('at least 3 results');
    expect(formToJobCreate({ ...DEFAULT_FORM, topic: 'x', numVideos: 3, sourceTypes: ['video', 'hn_story', 'podcast_episode'] }).ok).toBe(true);
  });

  it('templates store null for the default and the list otherwise', () => {
    const plain = formToTemplateParameters({ ...DEFAULT_FORM, topic: 'x' });
    expect(plain.ok && plain.params.source_types).toBe(null);
    const mixed = formToTemplateParameters(jobToFormState(MIXED_JOB));
    expect(mixed.ok && mixed.params.source_types).toEqual(['video', 'reddit_post']);
  });

  it('never sends sources for a channel run', () => {
    const form = { ...DEFAULT_FORM, jobType: 'channel' as const, channelList: '@veritasium', sourceTypes: ['hn_story' as const] };
    const result = formToJobCreate(form);
    expect(result.ok && 'source_types' in result.data).toBe(false);
  });

  it('offers X / Twitter only when /health reports tweet search on (T-1.5.9.3)', () => {
    const values = (caps: Record<string, boolean> | null) => offeredSourceTypes(caps).map((o) => o.value);
    expect(values(null)).not.toContain('tweet');
    expect(values({ twitter_search_enabled: false })).not.toContain('tweet');
    expect(values({ twitter_search_enabled: true })).toContain('tweet');
    expect(values({})).toEqual(['video', 'hn_story', 'mastodon_post', 'bluesky_post', 'podcast_episode']);
    expect(values({ reddit_search_enabled: true, article_search_enabled: true })).toContain('reddit_post');
  });

  it('flags a carried source the install no longer has, once capabilities are known', () => {
    expect(unavailableSourceTypes(['video', 'tweet'], null)).toEqual([]);
    expect(unavailableSourceTypes(['video', 'tweet'], { twitter_search_enabled: false })).toEqual(['tweet']);
    expect(unavailableSourceTypes(['video', 'tweet'], { twitter_search_enabled: true })).toEqual([]);
  });

  it('drafts restore the sources, tolerating junk and older drafts', () => {
    expect(parseDraft(JSON.stringify({ sourceTypes: ['hn_story', 'nope'] })).sourceTypes).toEqual(['hn_story']);
    expect(parseDraft(JSON.stringify({ sourceTypes: 'video' })).sourceTypes).toEqual(['video']);
    expect(parseDraft(JSON.stringify({ topic: 'x' })).sourceTypes).toEqual(['video']);
  });
});

describe('drafts', () => {
  it('tolerates an old draft without the new fields', () => {
    const form = parseDraft(JSON.stringify({ jobType: 'topic', topic: 'x', outputLength: 'weird' }));
    expect(form.topic).toBe('x');
    expect(form.outputLength).toBe('auto');
    expect(form.visualAnalysis).toBe(false);
  });

  it('falls back to the default on garbage', () => {
    expect(parseDraft('{not json')).toEqual(DEFAULT_FORM);
  });
});

describe('visual analysis hidden (D-105)', () => {
  afterEach(() => {
    featureFlags.visualAnalysis = false;
  });

  it('is hidden by default', () => {
    expect(featureFlags.visualAnalysis).toBe(false);
  });

  it('never sends a carried-over flag while hidden', () => {
    featureFlags.visualAnalysis = false;
    const result = formToJobCreate(jobToFormState(DEEP_VISUAL_JOB));
    expect(result.ok && 'visual_analysis' in result.data).toBe(false);
  });

  it('keeps the stored setting of a template so it returns intact', () => {
    featureFlags.visualAnalysis = false;
    const result = formToTemplateParameters({ ...jobToFormState(DEEP_VISUAL_JOB) });
    expect(result.ok && result.params.visual_analysis).toBe(true);
  });

  it('sends the flag again once the option is shown', () => {
    featureFlags.visualAnalysis = true;
    const result = formToJobCreate(jobToFormState(DEEP_VISUAL_JOB));
    expect(result.ok && result.data.visual_analysis).toBe(true);
  });
});
