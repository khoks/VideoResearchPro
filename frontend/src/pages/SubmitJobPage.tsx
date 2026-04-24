import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useCreateJob } from '../hooks/useJobs';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import { useJobStore } from '../stores/jobStore';
import type { Job, JobCreate, JobType } from '../types/job';

const FEATURE_UNAVAILABLE_MSG =
  'LLM-dependent feature is temporarily unavailable';

const CHANNEL_TYPE_OPTIONS = [
  'educational',
  'academic',
  'news',
  'entertainment',
  'podcast',
  'tutorial',
] as const;

type ChannelTypeOption = (typeof CHANNEL_TYPE_OPTIONS)[number];

const FORM_STATE_KEY = 'vrp:submit-form';

interface PersistedFormState {
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
}

const DEFAULT_FORM: PersistedFormState = {
  jobType: 'topic',
  topic: '',
  searchInstructions: '',
  numVideos: 10,
  minDuration: '',
  maxDuration: '',
  channelFilters: [],
  preferredChannels: '',
  channelList: '',
  videosPerChannel: 10,
  subscriptionChannels: '',
};

function loadForm(): PersistedFormState {
  if (typeof window === 'undefined') return DEFAULT_FORM;
  try {
    const raw = window.localStorage.getItem(FORM_STATE_KEY);
    if (!raw) return DEFAULT_FORM;
    const parsed = JSON.parse(raw) as Partial<PersistedFormState>;
    return {
      ...DEFAULT_FORM,
      ...parsed,
      channelFilters: Array.isArray(parsed.channelFilters)
        ? parsed.channelFilters.filter((c): c is ChannelTypeOption =>
            (CHANNEL_TYPE_OPTIONS as readonly string[]).includes(c),
          )
        : [],
    };
  } catch {
    return DEFAULT_FORM;
  }
}

// Translate a saved Job's submission parameters back into the shape the form
// state expects. Used when the user clicks "Duplicate / Re-run" on a job —
// we route here with { cloneFrom: job } in location.state and seed the form
// from those values, overriding any localStorage draft for this mount only.
function jobToFormState(job: Job): PersistedFormState {
  const channelLines = (list: string[] | null | undefined) =>
    list && list.length > 0 ? list.join('\n') : '';
  const validFilters = (job.channel_type_filters ?? []).filter(
    (c): c is ChannelTypeOption =>
      (CHANNEL_TYPE_OPTIONS as readonly string[]).includes(c),
  );
  return {
    jobType: job.job_type,
    topic: job.topic ?? '',
    searchInstructions: job.search_instructions ?? '',
    numVideos: job.num_videos ?? 10,
    minDuration: job.min_duration_minutes != null ? String(job.min_duration_minutes) : '',
    maxDuration: job.max_duration_minutes != null ? String(job.max_duration_minutes) : '',
    channelFilters: validFilters,
    preferredChannels: channelLines(job.preferred_channels),
    channelList: job.job_type === 'channel' ? channelLines(job.channel_list) : '',
    videosPerChannel: job.videos_per_channel ?? 10,
    subscriptionChannels:
      job.job_type === 'subscription' ? channelLines(job.channel_list) : '',
  };
}

// Accept @handle, youtube.com/@handle, /channel/UC..., /c/name, /user/name, or bare UC-IDs
const CHANNEL_URL_RE =
  /^(?:@[\w.-]{1,}|UC[\w-]{22}|(?:https?:\/\/)?(?:www\.)?youtube\.com\/(?:@[\w.-]{1,}|channel\/[\w-]{1,}|c\/[\w.-]{1,}|user\/[\w.-]{1,})\/?)$/i;

function parseChannelList(raw: string): string[] {
  return raw
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);
}

function validateChannels(lines: string[]): string[] {
  return lines.filter((line) => !CHANNEL_URL_RE.test(line));
}

export function SubmitJobPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const createJob = useCreateJob();
  const pushToast = useJobStore((s) => s.pushToast);
  const topicJobAvailable = useFeatureAvailable('topic_job');

  // When the user arrives via "Duplicate / Re-run" on a Job card, the source
  // job is passed in router state. Seed the form from it on first mount,
  // overriding any stale localStorage draft. Clone info is kept in component
  // state so the "Cloning from…" banner survives typing but disappears after
  // submission (which navigates away).
  const cloneFromInitial = (location.state as { cloneFrom?: Job } | null)?.cloneFrom ?? null;
  const [cloneFrom] = useState<Job | null>(cloneFromInitial);

  const [form, setForm] = useState<PersistedFormState>(() =>
    cloneFromInitial ? jobToFormState(cloneFromInitial) : loadForm(),
  );
  const [validationError, setValidationError] = useState<string | null>(null);

  // Persist on every change
  useEffect(() => {
    try {
      window.localStorage.setItem(FORM_STATE_KEY, JSON.stringify(form));
    } catch {
      // storage full / disabled — silently ignore
    }
  }, [form]);

  const update = <K extends keyof PersistedFormState>(key: K, value: PersistedFormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const toggleChannelFilter = (opt: ChannelTypeOption) => {
    setForm((f) => ({
      ...f,
      channelFilters: f.channelFilters.includes(opt)
        ? f.channelFilters.filter((x) => x !== opt)
        : [...f.channelFilters, opt],
    }));
  };

  // Quota estimate: ~100 units per search query × 3 queries + ~1 per video for details.
  // Channel jobs: channel lookup (~1/channel) + playlistItems (~1 per 50 videos) + ~1/video details.
  // Subscription jobs: ~100 units per channel to resolve + ~1 unit per 50 videos (walks all).
  const quotaEstimate = useMemo(() => {
    if (form.jobType === 'topic') {
      // 4-6 broad queries at 100 units each; pick a mid estimate.
      const broadSearches = 100 * 5;
      const details = Math.max(0, form.numVideos) * 1;
      // Each preferred channel: ~100 units to resolve (if search fallback hits)
      // + 1 unit to walk the uploads page + 1 unit of details per ~50 uploads.
      const preferredLines = parseChannelList(form.preferredChannels);
      const preferredCost = preferredLines.length * (100 + 1 + 1);
      return broadSearches + details + preferredCost;
    }
    if (form.jobType === 'subscription') {
      // Video count is unknown until resolve; assume a large channel (~500 videos) as upper estimate.
      const channels = parseChannelList(form.subscriptionChannels).length;
      const playlistCalls = channels * Math.ceil(500 / 50);
      return channels * 100 + playlistCalls;
    }
    const channels = parseChannelList(form.channelList).length;
    const playlistCalls = channels * Math.max(1, Math.ceil(form.videosPerChannel / 50));
    const details = channels * form.videosPerChannel;
    return channels + playlistCalls + details;
  }, [
    form.jobType,
    form.numVideos,
    form.channelList,
    form.videosPerChannel,
    form.subscriptionChannels,
    form.preferredChannels,
  ]);

  const topicBlocked = form.jobType === 'topic' && !topicJobAvailable;
  const submitDisabled = createJob.isPending || topicBlocked;

  const invalidChannels = useMemo(() => {
    if (form.jobType === 'channel') return validateChannels(parseChannelList(form.channelList));
    if (form.jobType === 'subscription')
      return validateChannels(parseChannelList(form.subscriptionChannels));
    return [];
  }, [form.jobType, form.channelList, form.subscriptionChannels]);

  // Preferred-channels validation runs independently of the main channel list
  // because it appears only on the topic-job tab.
  const invalidPreferredChannels = useMemo(() => {
    if (form.jobType !== 'topic') return [];
    const lines = parseChannelList(form.preferredChannels);
    return validateChannels(lines);
  }, [form.jobType, form.preferredChannels]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);

    const data: JobCreate = { job_type: form.jobType };

    if (form.jobType === 'topic') {
      if (!form.topic.trim()) {
        setValidationError('Topic is required.');
        return;
      }
      data.topic = form.topic.trim();
      data.num_videos = form.numVideos;
      data.search_instructions = form.searchInstructions || undefined;
      if (form.minDuration) data.min_duration_minutes = parseInt(form.minDuration, 10);
      if (form.maxDuration) data.max_duration_minutes = parseInt(form.maxDuration, 10);
      if (form.channelFilters.length > 0) data.channel_type_filters = [...form.channelFilters];

      const preferredLines = parseChannelList(form.preferredChannels);
      if (preferredLines.length > 0) {
        const invalid = validateChannels(preferredLines);
        if (invalid.length > 0) {
          setValidationError(
            `Invalid preferred-channel entries: ${invalid.slice(0, 3).join(', ')}${
              invalid.length > 3 ? '...' : ''
            }`,
          );
          return;
        }
        data.preferred_channels = preferredLines;
      }
    } else {
      const raw = form.jobType === 'channel' ? form.channelList : form.subscriptionChannels;
      const lines = parseChannelList(raw);
      if (lines.length === 0) {
        setValidationError('Provide at least one channel URL, handle, or UC-ID.');
        return;
      }
      const invalid = validateChannels(lines);
      if (invalid.length > 0) {
        setValidationError(
          `Invalid channel entries: ${invalid.slice(0, 3).join(', ')}${invalid.length > 3 ? '...' : ''}`,
        );
        return;
      }
      data.channel_list = lines;
      if (form.jobType === 'channel') {
        data.videos_per_channel = form.videosPerChannel;
        data.num_videos = form.numVideos;
        if (form.minDuration) data.min_duration_minutes = parseInt(form.minDuration, 10);
        if (form.maxDuration) data.max_duration_minutes = parseInt(form.maxDuration, 10);
      }
    }

    try {
      const job = await createJob.mutateAsync(data);
      // Clear persisted form on successful submission
      try {
        window.localStorage.removeItem(FORM_STATE_KEY);
      } catch {
        /* ignore */
      }
      pushToast('success', 'Job submitted.');
      navigate(`/jobs/${job.id}`);
    } catch {
      // Global error toast is emitted by the MutationCache; nothing to do here.
    }
  };

  const handleReset = () => {
    setForm(DEFAULT_FORM);
    setValidationError(null);
    try {
      window.localStorage.removeItem(FORM_STATE_KEY);
    } catch {
      /* ignore */
    }
  };

  return (
    <div style={{ maxWidth: 700, margin: '0 auto' }}>
      {cloneFrom && (
        <div style={{
          background: 'rgba(102, 126, 234, 0.08)',
          border: '1px solid rgba(102, 126, 234, 0.35)',
          borderRadius: 8,
          padding: '0.7rem 0.9rem',
          marginBottom: '1rem',
          fontSize: '0.85rem',
          color: 'var(--color-text)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '0.75rem',
          flexWrap: 'wrap',
        }}>
          <span>
            Cloning from job{' '}
            <a
              href={`/jobs/${cloneFrom.id}`}
              onClick={(e) => { e.preventDefault(); navigate(`/jobs/${cloneFrom.id}`); }}
              style={{ color: 'var(--color-accent)', fontWeight: 600, textDecoration: 'none' }}
            >
              {cloneFrom.id.slice(0, 8)}
            </a>
            . Fields below are pre-filled from that submission — edit freely; a
            new job with a new ID will be created on submit.
          </span>
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    marginBottom: '1.5rem' }}>
        <h2 style={{ color: 'var(--color-text)' }}>
          {cloneFrom ? 'Duplicate Research Job' : 'Submit New Research Job'}
        </h2>
        <button
          type="button"
          onClick={handleReset}
          style={{
            background: 'transparent',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-muted)',
            padding: '0.4rem 0.9rem',
            borderRadius: 6,
            cursor: 'pointer',
            fontSize: '0.8rem',
          }}
        >
          Reset form
        </button>
      </div>

      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
        <TypeToggle active={form.jobType === 'topic'} onClick={() => update('jobType', 'topic')}>
          Topic Research
        </TypeToggle>
        <TypeToggle active={form.jobType === 'channel'} onClick={() => update('jobType', 'channel')}>
          Channel List
        </TypeToggle>
        <TypeToggle
          active={form.jobType === 'subscription'}
          onClick={() => update('jobType', 'subscription')}
        >
          Channel Subscription
        </TypeToggle>
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {form.jobType === 'topic' && (
          <>
            <Field label="Research Topic *">
              <input
                value={form.topic}
                onChange={(e) => update('topic', e.target.value)}
                placeholder="e.g. Quantum Computing breakthroughs 2025"
                required
              />
            </Field>
            <Field label="Search Instructions (optional)">
              <textarea
                value={form.searchInstructions}
                onChange={(e) => update('searchInstructions', e.target.value)}
                placeholder={
                  'Semantic guidance for the Search Agent. Good examples:\n' +
                  '  - "Prefer recent 2026 uploads, skip anything older than 12 months."\n' +
                  '  - "Favor skeptical / critical perspectives over marketing clips."\n' +
                  "Don't list channel names here — use the Preferred Channels field below instead."
                }
                rows={3}
              />
            </Field>
            <Field label="Preferred Channels (optional)">
              <textarea
                value={form.preferredChannels}
                onChange={(e) => update('preferredChannels', e.target.value)}
                placeholder={
                  '@nateb.jones\n@dwarkeshpatel\nhttps://youtube.com/@andrewberman\nUCx...'
                }
                rows={4}
              />
              <span style={{ fontSize: '0.75rem', color: 'var(--color-text-faint)' }}>
                One per line: @handles, channel URLs, or UC-IDs. The agent will walk each
                channel&apos;s recent uploads and surface anything topic-relevant alongside a
                broad YouTube search.
              </span>
            </Field>
            {invalidPreferredChannels.length > 0 && (
              <p style={{ margin: 0, fontSize: '0.8rem', color: '#ef4444' }}>
                Invalid preferred-channel entries:{' '}
                {invalidPreferredChannels.slice(0, 3).join(', ')}
                {invalidPreferredChannels.length > 3
                  ? `, +${invalidPreferredChannels.length - 3} more`
                  : ''}
              </p>
            )}
            <Field label="Number of Videos">
              <input
                type="number"
                value={form.numVideos}
                onChange={(e) => update('numVideos', parseInt(e.target.value || '0', 10) || 0)}
                min={1}
                max={100}
              />
            </Field>
            <div className="form-row" style={{ display: 'flex', gap: '1rem' }}>
              <Field label="Min Duration (minutes)">
                <input
                  type="number"
                  value={form.minDuration}
                  onChange={(e) => update('minDuration', e.target.value)}
                  placeholder="Any"
                  min={1}
                />
              </Field>
              <Field label="Max Duration (minutes)">
                <input
                  type="number"
                  value={form.maxDuration}
                  onChange={(e) => update('maxDuration', e.target.value)}
                  placeholder="Any"
                  min={1}
                />
              </Field>
            </div>
            <Field label="Channel Type Filters (optional)">
              <div style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: '0.4rem',
                padding: '0.5rem',
                border: '1px solid var(--color-border)',
                borderRadius: 8,
                background: 'var(--color-input-bg)',
              }}>
                {CHANNEL_TYPE_OPTIONS.map((opt) => {
                  const selected = form.channelFilters.includes(opt);
                  return (
                    <button
                      type="button"
                      key={opt}
                      onClick={() => toggleChannelFilter(opt)}
                      aria-pressed={selected}
                      style={{
                        background: selected ? 'var(--color-accent)' : 'transparent',
                        color: selected ? '#fff' : 'var(--color-text-muted)',
                        border: `1px solid ${selected ? 'var(--color-accent)' : 'var(--color-border-strong)'}`,
                        padding: '0.3rem 0.8rem',
                        borderRadius: 999,
                        fontSize: '0.8rem',
                        cursor: 'pointer',
                        fontWeight: selected ? 600 : 500,
                        textTransform: 'capitalize',
                      }}
                    >
                      {opt}
                    </button>
                  );
                })}
              </div>
            </Field>
          </>
        )}

        {form.jobType === 'channel' && (
          <>
            <Field label="YouTube Channels (one per line) *">
              <textarea
                value={form.channelList}
                onChange={(e) => update('channelList', e.target.value)}
                placeholder={'@3blue1brown\n@Veritasium\nhttps://youtube.com/@kurzgesagt'}
                rows={5}
                required
              />
            </Field>
            {invalidChannels.length > 0 && (
              <p style={{
                margin: 0,
                fontSize: '0.8rem',
                color: '#ef4444',
              }}>
                Invalid entries: {invalidChannels.slice(0, 3).join(', ')}
                {invalidChannels.length > 3 ? `, +${invalidChannels.length - 3} more` : ''}
              </p>
            )}
            <Field label="Videos per Channel">
              <input
                type="number"
                value={form.videosPerChannel}
                onChange={(e) =>
                  update('videosPerChannel', parseInt(e.target.value || '0', 10) || 0)
                }
                min={1}
                max={50}
              />
            </Field>
            <div className="form-row" style={{ display: 'flex', gap: '1rem' }}>
              <Field label="Min Duration (minutes)">
                <input
                  type="number"
                  value={form.minDuration}
                  onChange={(e) => update('minDuration', e.target.value)}
                  placeholder="Any"
                  min={1}
                />
              </Field>
              <Field label="Max Duration (minutes)">
                <input
                  type="number"
                  value={form.maxDuration}
                  onChange={(e) => update('maxDuration', e.target.value)}
                  placeholder="Any"
                  min={1}
                />
              </Field>
            </div>
          </>
        )}

        {form.jobType === 'subscription' && (
          <>
            <div style={{
              background: 'rgba(234, 179, 8, 0.08)',
              border: '1px solid rgba(234, 179, 8, 0.4)',
              borderRadius: 8,
              padding: '0.8rem 1rem',
              fontSize: '0.85rem',
              color: 'var(--color-text)',
              lineHeight: 1.5,
            }}>
              <strong>Note:</strong> Subscription jobs ingest <strong>every</strong> video from each
              channel. Videos without YouTube captions will be transcribed with OpenAI Whisper
              (this can incur significant API costs on large channels). Videos are added to the
              shared library and reused across all future jobs.
            </div>
            <Field label="YouTube Channels (one per line) *">
              <textarea
                value={form.subscriptionChannels}
                onChange={(e) => update('subscriptionChannels', e.target.value)}
                placeholder={'@3blue1brown\n@Veritasium\nUCsXVk37bltHxD1rDPwtNM8Q'}
                rows={5}
                required
              />
            </Field>
            {invalidChannels.length > 0 && (
              <p style={{
                margin: 0,
                fontSize: '0.8rem',
                color: '#ef4444',
              }}>
                Invalid entries: {invalidChannels.slice(0, 3).join(', ')}
                {invalidChannels.length > 3 ? `, +${invalidChannels.length - 3} more` : ''}
              </p>
            )}
          </>
        )}

        <div style={{
          background: 'var(--color-surface-alt)',
          border: '1px solid var(--color-border)',
          borderRadius: 8,
          padding: '0.7rem 0.9rem',
          fontSize: '0.82rem',
          color: 'var(--color-text-muted)',
        }}>
          <strong style={{ color: 'var(--color-text)' }}>Estimated YouTube quota:</strong>{' '}
          ~{quotaEstimate.toLocaleString()} units
          <span style={{ marginLeft: '0.5rem', color: 'var(--color-text-faint)' }}>
            (daily free quota: 10,000)
          </span>
          {form.jobType === 'subscription' && (
            <div style={{ marginTop: '0.4rem', color: 'var(--color-text-faint)' }}>
              Approximate cost: 100 units per channel to resolve + ~1 unit per 50 videos on the
              channel. A large channel with 500 videos is approximately 110 units.
            </div>
          )}
        </div>

        {validationError && (
          <p style={{ color: '#ef4444', margin: 0, fontSize: '0.85rem' }}>{validationError}</p>
        )}

        {topicBlocked && (
          <p style={{ color: '#b45309', margin: 0, fontSize: '0.85rem' }}>
            {FEATURE_UNAVAILABLE_MSG}. Topic research depends on the search LLM — try
            again once it recovers, or submit a channel / subscription job instead.
          </p>
        )}

        <button
          type="submit"
          disabled={submitDisabled}
          title={topicBlocked ? FEATURE_UNAVAILABLE_MSG : undefined}
          style={{
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            color: '#fff',
            border: 'none',
            padding: '0.8rem 2rem',
            borderRadius: 8,
            fontSize: '1rem',
            fontWeight: 600,
            cursor: submitDisabled ? 'not-allowed' : 'pointer',
            marginTop: '0.5rem',
            opacity: submitDisabled ? 0.6 : 1,
          }}
        >
          {createJob.isPending ? 'Submitting...' : 'Submit Job'}
        </button>
      </form>
    </div>
  );
}

function TypeToggle({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} style={{
      padding: '0.6rem 1.5rem', borderRadius: 8, border: '2px solid',
      borderColor: active ? 'var(--color-accent)' : 'var(--color-border)',
      background: active ? 'var(--color-accent)' : 'var(--color-surface)',
      color: active ? '#fff' : 'var(--color-text-muted)',
      fontWeight: 600, cursor: 'pointer', transition: 'all 0.2s',
    }}>
      {children}
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', flex: 1 }}>
      <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--color-text-muted)' }}>{label}</span>
      {children}
    </label>
  );
}
