import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useCreateJob } from '../hooks/useJobs';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import { useTierCapabilities } from '../hooks/useTierCapabilities';
import { useJobStore } from '../stores/jobStore';
import {
  Button,
  Card,
  FormField,
  Input,
  Select,
  Textarea,
} from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import {
  fonts,
  fontSize,
  fontWeight,
  lineHeight,
  measure,
  radius,
  space,
} from '../theme';
import type { Job, JobCreate, JobType, OutputLength } from '../types/job';

const FEATURE_UNAVAILABLE_MSG = 'LLM-dependent feature is temporarily unavailable';

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
  outputLength: OutputLength;
}

const DEFAULT_FORM: PersistedFormState = {
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
    outputLength: 'auto',
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
  const c = useColors();
  const createJob = useCreateJob();
  const pushToast = useJobStore((s) => s.pushToast);
  const topicJobAvailable = useFeatureAvailable('topic_job');
  const { tier, numVideosCap } = useTierCapabilities();

  const cloneFromInitial = (location.state as { cloneFrom?: Job } | null)?.cloneFrom ?? null;
  const [cloneFrom] = useState<Job | null>(cloneFromInitial);

  const [form, setForm] = useState<PersistedFormState>(() =>
    cloneFromInitial ? jobToFormState(cloneFromInitial) : loadForm(),
  );
  const [validationError, setValidationError] = useState<string | null>(null);

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

  const quotaEstimate = useMemo(() => {
    if (form.jobType === 'topic') {
      const broadSearches = 100 * 5;
      const details = Math.max(0, form.numVideos) * 1;
      const preferredLines = parseChannelList(form.preferredChannels);
      const preferredCost = preferredLines.length * (100 + 1 + 1);
      return broadSearches + details + preferredCost;
    }
    if (form.jobType === 'subscription') {
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

  const invalidPreferredChannels = useMemo(() => {
    if (form.jobType !== 'topic') return [];
    const lines = parseChannelList(form.preferredChannels);
    return validateChannels(lines);
  }, [form.jobType, form.preferredChannels]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);

    const data: JobCreate = { job_type: form.jobType };
    if (form.outputLength !== 'auto') data.output_length = form.outputLength;

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
              invalid.length > 3 ? '…' : ''
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
          `Invalid channel entries: ${invalid.slice(0, 3).join(', ')}${invalid.length > 3 ? '…' : ''}`,
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
      try {
        window.localStorage.removeItem(FORM_STATE_KEY);
      } catch {
        /* ignore */
      }
      pushToast('success', 'Research submitted.');
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
    <div style={{ maxWidth: measure.form, margin: '0 auto' }}>
      {cloneFrom && (
        <Card
          sunken
          style={{
            marginBottom: space['4'],
            padding: `${space['3']} ${space['4']}`,
            display: 'flex',
            gap: space['3'],
            alignItems: 'center',
            flexWrap: 'wrap',
          }}
        >
          <span
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              color: c.textSecondary,
            }}
          >
            Cloning from run{' '}
            <a
              href={`/jobs/${cloneFrom.id}`}
              onClick={(e) => {
                e.preventDefault();
                navigate(`/jobs/${cloneFrom.id}`);
              }}
              style={{
                color: c.accent,
                fontWeight: fontWeight.semibold,
                textDecoration: 'none',
              }}
            >
              {cloneFrom.id.slice(0, 8)}
            </a>
            . Fields below are pre-filled from that submission — edit freely; a new run with a new ID will be created on submit.
          </span>
        </Card>
      )}

      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          gap: space['3'],
          marginBottom: space['5'],
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h1
            style={{
              fontFamily: fonts.display,
              fontSize: fontSize['2xl'],
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
              margin: 0,
              lineHeight: lineHeight.tight,
            }}
          >
            {cloneFrom ? 'Duplicate a research run' : 'Begin a new research run'}
          </h1>
          <p
            style={{
              fontFamily: fonts.body,
              fontStyle: 'italic',
              fontSize: fontSize.sm,
              color: c.textMuted,
              margin: `${space['2']} 0 0`,
              maxWidth: measure.reading,
            }}
          >
            Curate the voices. The library will remember them.
          </p>
        </div>
        <Button size="sm" variant="tertiary" onClick={handleReset}>
          Reset form
        </Button>
      </header>

      <div
        role="tablist"
        aria-label="Research type"
        style={{
          display: 'flex',
          gap: space['1'],
          marginBottom: space['5'],
          borderBottom: `1px solid ${c.border}`,
        }}
      >
        <TypeToggle active={form.jobType === 'topic'} onClick={() => update('jobType', 'topic')}>
          Topic
        </TypeToggle>
        <TypeToggle
          active={form.jobType === 'channel'}
          onClick={() => update('jobType', 'channel')}
        >
          Channels
        </TypeToggle>
        <TypeToggle
          active={form.jobType === 'subscription'}
          onClick={() => update('jobType', 'subscription')}
        >
          Subscription
        </TypeToggle>
      </div>

      <Card>
        <form
          onSubmit={handleSubmit}
          style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}
        >
          {form.jobType === 'topic' && (
            <>
              <FormField label="Research topic" required>
                {(id) => (
                  <Input
                    id={id}
                    value={form.topic}
                    onChange={(e) => update('topic', e.target.value)}
                    placeholder="e.g. Quantum Computing breakthroughs 2025"
                    required
                  />
                )}
              </FormField>
              <FormField
                label="Search instructions"
                optional
                helperText="Semantic guidance for the Search Agent. Don't list channel names here — use Preferred Channels below."
              >
                {(id) => (
                  <Textarea
                    id={id}
                    value={form.searchInstructions}
                    onChange={(e) => update('searchInstructions', e.target.value)}
                    placeholder={
                      'Good examples:\n  - "Prefer recent 2026 uploads, skip anything older than 12 months."\n  - "Favor skeptical / critical perspectives over marketing clips."'
                    }
                    rows={3}
                  />
                )}
              </FormField>
              <FormField
                label="Preferred channels"
                optional
                helperText="One per line: @handles, channel URLs, or UC-IDs. The agent walks each channel's recent uploads alongside a broad YouTube search."
                errorText={
                  invalidPreferredChannels.length > 0
                    ? `Invalid entries: ${invalidPreferredChannels.slice(0, 3).join(', ')}${
                        invalidPreferredChannels.length > 3
                          ? `, +${invalidPreferredChannels.length - 3} more`
                          : ''
                      }`
                    : undefined
                }
              >
                {(id) => (
                  <Textarea
                    id={id}
                    value={form.preferredChannels}
                    onChange={(e) => update('preferredChannels', e.target.value)}
                    placeholder={
                      '@nateb.jones\n@dwarkeshpatel\nhttps://youtube.com/@andrewberman\nUCx…'
                    }
                    rows={4}
                    invalid={invalidPreferredChannels.length > 0}
                  />
                )}
              </FormField>
              <FormField
                label="Number of videos"
                helperText={`Your ${tier} plan allows up to ${numVideosCap} videos per research run.`}
              >
                {(id) => (
                  <Input
                    id={id}
                    type="number"
                    value={form.numVideos}
                    onChange={(e) => update('numVideos', parseInt(e.target.value || '0', 10) || 0)}
                    min={1}
                    max={numVideosCap}
                  />
                )}
              </FormField>
              {/* R4: optional depth override. Defaults to Auto so the control
                  is additive — a user who ignores it gets the corpus-size
                  default, which is the behaviour that already shipped. */}
              <FormField
                label="Report depth"
                helperText="Auto sizes the report to how much material the corpus actually yields."
              >
                {(id) => (
                  <Select
                    id={id}
                    value={form.outputLength}
                    onChange={(e) => update('outputLength', e.target.value as OutputLength)}
                  >
                    <option value="auto">Auto (recommended)</option>
                    <option value="brief">Brief — headline findings only</option>
                    <option value="standard">Standard</option>
                    <option value="deep">Deep — develop the reasoning</option>
                  </Select>
                )}
              </FormField>
              <div className="form-row" style={{ display: 'flex', gap: space['4'] }}>
                <FormField label="Min duration (minutes)" style={{ flex: 1 }}>
                  {(id) => (
                    <Input
                      id={id}
                      type="number"
                      value={form.minDuration}
                      onChange={(e) => update('minDuration', e.target.value)}
                      placeholder="Any"
                      min={1}
                    />
                  )}
                </FormField>
                <FormField label="Max duration (minutes)" style={{ flex: 1 }}>
                  {(id) => (
                    <Input
                      id={id}
                      type="number"
                      value={form.maxDuration}
                      onChange={(e) => update('maxDuration', e.target.value)}
                      placeholder="Any"
                      min={1}
                    />
                  )}
                </FormField>
              </div>
              <FormField label="Channel-type filters" optional>
                {() => (
                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: space['2'],
                      padding: space['2'],
                      border: `1px solid ${c.border}`,
                      borderRadius: radius.md,
                      background: c.surfaceAlt,
                    }}
                  >
                    {CHANNEL_TYPE_OPTIONS.map((opt) => {
                      const selected = form.channelFilters.includes(opt);
                      return (
                        <button
                          type="button"
                          key={opt}
                          onClick={() => toggleChannelFilter(opt)}
                          aria-pressed={selected}
                          style={{
                            background: selected ? c.accent : 'transparent',
                            color: selected ? c.textInverted : c.textSecondary,
                            border: `1px solid ${selected ? c.accent : c.borderStrong}`,
                            padding: `${space['1']} ${space['3']}`,
                            borderRadius: radius.pill,
                            fontFamily: fonts.ui,
                            fontSize: fontSize.xs,
                            cursor: 'pointer',
                            fontWeight: selected ? fontWeight.semibold : fontWeight.medium,
                            textTransform: 'capitalize',
                            letterSpacing: '0.02em',
                          }}
                        >
                          {opt}
                        </button>
                      );
                    })}
                  </div>
                )}
              </FormField>
            </>
          )}

          {form.jobType === 'channel' && (
            <>
              <FormField
                label="YouTube channels"
                required
                helperText="One per line."
                errorText={
                  invalidChannels.length > 0
                    ? `Invalid entries: ${invalidChannels.slice(0, 3).join(', ')}${
                        invalidChannels.length > 3 ? `, +${invalidChannels.length - 3} more` : ''
                      }`
                    : undefined
                }
              >
                {(id) => (
                  <Textarea
                    id={id}
                    value={form.channelList}
                    onChange={(e) => update('channelList', e.target.value)}
                    placeholder={'@3blue1brown\n@Veritasium\nhttps://youtube.com/@kurzgesagt'}
                    rows={5}
                    required
                    invalid={invalidChannels.length > 0}
                  />
                )}
              </FormField>
              <FormField label="Videos per channel">
                {(id) => (
                  <Input
                    id={id}
                    type="number"
                    value={form.videosPerChannel}
                    onChange={(e) =>
                      update('videosPerChannel', parseInt(e.target.value || '0', 10) || 0)
                    }
                    min={1}
                    max={50}
                  />
                )}
              </FormField>
              <div className="form-row" style={{ display: 'flex', gap: space['4'] }}>
                <FormField label="Min duration (minutes)" style={{ flex: 1 }}>
                  {(id) => (
                    <Input
                      id={id}
                      type="number"
                      value={form.minDuration}
                      onChange={(e) => update('minDuration', e.target.value)}
                      placeholder="Any"
                      min={1}
                    />
                  )}
                </FormField>
                <FormField label="Max duration (minutes)" style={{ flex: 1 }}>
                  {(id) => (
                    <Input
                      id={id}
                      type="number"
                      value={form.maxDuration}
                      onChange={(e) => update('maxDuration', e.target.value)}
                      placeholder="Any"
                      min={1}
                    />
                  )}
                </FormField>
              </div>
            </>
          )}

          {form.jobType === 'subscription' && (
            <>
              <div
                role="note"
                style={{
                  background: c.warnSubtle,
                  border: `1px solid ${c.warn}`,
                  borderRadius: radius.md,
                  padding: `${space['3']} ${space['4']}`,
                  fontFamily: fonts.body,
                  fontSize: fontSize.sm,
                  color: c.textPrimary,
                  lineHeight: lineHeight.normal,
                }}
              >
                <strong style={{ color: c.warn, fontWeight: fontWeight.semibold }}>Note.</strong>{' '}
                Subscription runs ingest <strong>every</strong> video from each channel. Videos without YouTube captions will be transcribed with OpenAI Whisper (this can incur significant API costs on large channels). Videos are added to the shared library and reused across all future runs.
              </div>
              <FormField
                label="YouTube channels"
                required
                helperText="One per line."
                errorText={
                  invalidChannels.length > 0
                    ? `Invalid entries: ${invalidChannels.slice(0, 3).join(', ')}${
                        invalidChannels.length > 3 ? `, +${invalidChannels.length - 3} more` : ''
                      }`
                    : undefined
                }
              >
                {(id) => (
                  <Textarea
                    id={id}
                    value={form.subscriptionChannels}
                    onChange={(e) => update('subscriptionChannels', e.target.value)}
                    placeholder={'@3blue1brown\n@Veritasium\nUCsXVk37bltHxD1rDPwtNM8Q'}
                    rows={5}
                    required
                    invalid={invalidChannels.length > 0}
                  />
                )}
              </FormField>
            </>
          )}

          <div
            style={{
              background: c.surfaceAlt,
              border: `1px solid ${c.border}`,
              borderRadius: radius.md,
              padding: `${space['3']} ${space['4']}`,
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              color: c.textSecondary,
              lineHeight: lineHeight.snug,
            }}
          >
            <strong style={{ color: c.textPrimary, fontWeight: fontWeight.semibold }}>
              Estimated YouTube quota:
            </strong>{' '}
            <span
              style={{
                fontFamily: fonts.mono,
                color: c.textPrimary,
                fontWeight: fontWeight.medium,
              }}
            >
              ~{quotaEstimate.toLocaleString()} units
            </span>
            <span style={{ marginLeft: space['2'], color: c.textMuted }}>
              (daily free quota: 10,000)
            </span>
            {form.jobType === 'subscription' && (
              <div style={{ marginTop: space['2'], color: c.textMuted }}>
                Approximate cost: 100 units per channel to resolve + ~1 unit per 50 videos on the channel. A large channel with 500 videos is approximately 110 units.
              </div>
            )}
          </div>

          {validationError && (
            <p
              role="alert"
              style={{
                margin: 0,
                padding: space['3'],
                background: c.errorSubtle,
                border: `1px solid ${c.error}`,
                borderRadius: radius.md,
                color: c.error,
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                fontWeight: fontWeight.medium,
              }}
            >
              {validationError}
            </p>
          )}

          {topicBlocked && (
            <p
              role="alert"
              style={{
                margin: 0,
                padding: space['3'],
                background: c.warnSubtle,
                border: `1px solid ${c.warn}`,
                borderRadius: radius.md,
                color: c.warn,
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
              }}
            >
              {FEATURE_UNAVAILABLE_MSG}. Topic research depends on the search LLM — try again once it recovers, or submit a channel / subscription run instead.
            </p>
          )}

          <div style={{ marginTop: space['2'] }}>
            <Button
              type="submit"
              disabled={submitDisabled}
              loading={createJob.isPending}
              title={topicBlocked ? FEATURE_UNAVAILABLE_MSG : undefined}
              style={{ minWidth: 160 }}
            >
              Begin research
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

function TypeToggle({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  const c = useColors();
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      style={{
        background: 'transparent',
        color: active ? c.accent : c.textSecondary,
        border: 'none',
        borderBottom: `2px solid ${active ? c.accent : 'transparent'}`,
        padding: `${space['2']} ${space['4']}`,
        marginBottom: -1,
        cursor: 'pointer',
        fontFamily: fonts.ui,
        fontWeight: active ? fontWeight.semibold : fontWeight.medium,
        fontSize: fontSize.sm,
        letterSpacing: '0.02em',
      }}
    >
      {children}
    </button>
  );
}
