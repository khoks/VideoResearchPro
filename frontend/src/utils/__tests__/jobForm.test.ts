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
  parseDraft,
  templateNeedsChannels,
  templateToFormState,
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
