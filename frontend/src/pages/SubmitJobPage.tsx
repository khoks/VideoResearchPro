import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useCreateJob } from '../hooks/useJobs';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import { useCapability } from '../hooks/useCapability';
import { VisualAnalysisOption } from '../components/jobs/VisualAnalysisOption';
import { SourceTypePicker } from '../components/jobs/SourceTypePicker';
import { useSystemStatusStore } from '../stores/systemStatusStore';
import { featureFlags } from '../config/features';
import { useTierCapabilities } from '../hooks/useTierCapabilities';
import { useCreateTemplate, useJobTemplates, useUpdateTemplate } from '../hooks/useJobTemplates';
import { SaveTemplateModal, TemplatePicker } from '../components/templates';
import type { JobTemplate } from '../services/jobTemplatesApi';
import {
  CHANNEL_TYPE_OPTIONS,
  DEFAULT_FORM,
  formToJobCreate,
  formToTemplateParameters,
  jobToFormState,
  parseChannelList,
  parseDraft,
  isDefaultSourceTypes,
  sourceTypeLabel,
  sourceTypeShares,
  templateNeedsChannels,
  templateToFormState,
  unavailableSourceTypes,
  validateChannels,
  type ChannelTypeOption,
  type JobFormState,
} from '../utils/jobForm';
import { useJobStore } from '../stores/jobStore';
import { apiErrorMessage, isDocumentCapRefusal } from '../utils/apiError';
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
import type { Job, JobType, OutputLength } from '../types/job';

const FEATURE_UNAVAILABLE_MSG = 'LLM-dependent feature is temporarily unavailable';

const FORM_STATE_KEY = 'vrp:submit-form';

type PersistedFormState = JobFormState;

function loadForm(): PersistedFormState {
  if (typeof window === 'undefined') return DEFAULT_FORM;
  try {
    return parseDraft(window.localStorage.getItem(FORM_STATE_KEY));
  } catch {
    return DEFAULT_FORM;
  }
}

interface TemplateOrigin {
  id: string;
  name: string;
  version: number;
  builtin: boolean;
  jobType: JobType;
  problems: string[];
  needsChannels: boolean;
}

export function SubmitJobPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const c = useColors();
  const createJob = useCreateJob();
  const pushToast = useJobStore((s) => s.pushToast);
  const topicJobAvailable = useFeatureAvailable('topic_job');
  const visualModelsAvailable = useFeatureAvailable('visual_analysis');
  const visualInstallEnabled = useCapability('visual_analysis_enabled');
  // S-1.5.13: which credential-gated sources this install can search.
  const capabilities = useSystemStatusStore((s) => s.capabilities);
  const { tier, numVideosCap } = useTierCapabilities();

  const routeState = location.state as { cloneFrom?: Job; fromTemplateId?: string } | null;
  const cloneFromInitial = routeState?.cloneFrom ?? null;
  const [cloneFrom, setCloneFrom] = useState<Job | null>(cloneFromInitial);

  // E-8.6 templates: the origin is recorded on the run as provenance.
  const templatesQuery = useJobTemplates();
  const createTemplate = useCreateTemplate();
  const updateTemplate = useUpdateTemplate();
  const [fromTemplate, setFromTemplate] = useState<TemplateOrigin | null>(null);
  const [savingTemplate, setSavingTemplate] = useState(false);

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

  const applyTemplate = (t: JobTemplate) => {
    setForm((f) => templateToFormState(t.parameters, f.topic));
    setFromTemplate({
      id: t.id,
      name: t.name,
      version: t.version,
      builtin: t.builtin,
      jobType: t.job_type,
      problems: t.problems,
      needsChannels: templateNeedsChannels(t.parameters),
    });
    setCloneFrom(null);
    setValidationError(null);
  };

  // "Use" on the Templates page arrives with the id; apply it once loaded.
  const pendingTemplateId = useRef<string | null>(routeState?.fromTemplateId ?? null);
  useEffect(() => {
    const id = pendingTemplateId.current;
    if (!id || !templatesQuery.data) return;
    pendingTemplateId.current = null;
    const t = templatesQuery.data.find((x) => x.id === id);
    if (t) applyTemplate(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templatesQuery.data]);

  const saveChangesToTemplate = () => {
    if (!fromTemplate) return;
    const result = formToTemplateParameters(form);
    if (!result.ok) {
      setValidationError(result.error);
      return;
    }
    const before = fromTemplate.version;
    updateTemplate.mutate(
      { id: fromTemplate.id, body: { parameters: result.params } },
      {
        onSuccess: (t) => {
          setFromTemplate((o) => (o ? { ...o, version: t.version, problems: t.problems } : o));
          pushToast(
            'success',
            t.version === before ? 'Nothing changed; the template is as it was.' : `Saved as version ${t.version}.`,
          );
        },
      },
    );
  };

  const saveFormAsTemplate = async (values: { name: string; description: string | null }) => {
    const result = formToTemplateParameters(form);
    if (!result.ok) throw new Error(result.error);
    const t = await createTemplate.mutateAsync({ ...values, parameters: result.params });
    setFromTemplate({
      id: t.id,
      name: t.name,
      version: t.version,
      builtin: false,
      jobType: t.job_type,
      problems: t.problems,
      needsChannels: templateNeedsChannels(t.parameters),
    });
    pushToast('success', `Saved template "${t.name}".`);
  };

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
      // S-1.5.13: only the YouTube source spends YouTube quota, and only
      // on its share of the run's results.
      if (!form.sourceTypes.includes('video')) return 0;
      const broadSearches = 100 * 5;
      const details = Math.max(0, sourceTypeShares(form.numVideos, form.sourceTypes).video ?? 0) * 1;
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
    form.sourceTypes,
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

    const result = formToJobCreate(form);
    if (!result.ok) {
      setValidationError(result.error);
      return;
    }
    const unavailable =
      form.jobType === 'topic' ? unavailableSourceTypes(form.sourceTypes, capabilities) : [];
    if (unavailable.length > 0) {
      const one = unavailable.length === 1;
      setValidationError(
        `${unavailable.map(sourceTypeLabel).join(', ')} ${one ? 'is' : 'are'} not set up on this install; remove ${
          one ? 'it' : 'them'
        } from the sources to submit.`,
      );
      return;
    }
    const data = result.data;
    // Switching the research type leaves the template behind.
    const provenance =
      fromTemplate && fromTemplate.jobType === form.jobType
        ? { templateId: fromTemplate.id, templateVersion: fromTemplate.version }
        : undefined;

    try {
      const job = await createJob.mutateAsync({ data, provenance });
      try {
        window.localStorage.removeItem(FORM_STATE_KEY);
      } catch {
        /* ignore */
      }
      pushToast('success', 'Research submitted.');
      navigate(`/jobs/${job.id}`);
    } catch (err) {
      // A full library refuses a subscription run (429, T-5.2.10): say why in
      // the form, where the run was started. Every other failure is toasted
      // by the MutationCache.
      if (isDocumentCapRefusal(err)) {
        setValidationError(
          apiErrorMessage(err, "Your library is at your plan's document cap, so this run was not started."),
        );
      }
    }
  };

  const handleReset = () => {
    setForm(DEFAULT_FORM);
    setValidationError(null);
    setFromTemplate(null);
    setCloneFrom(null);
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
            {cloneFrom
              ? 'Duplicate a research run'
              : fromTemplate
                ? 'Research from a template'
                : 'Begin a new research run'}
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

      <TemplatePicker templates={templatesQuery.data ?? []} onPick={applyTemplate} />

      {fromTemplate && (
        <TemplateOriginBanner
          origin={fromTemplate}
          typeChanged={fromTemplate.jobType !== form.jobType}
          saving={updateTemplate.isPending}
          onSaveChanges={saveChangesToTemplate}
          onDetach={() => setFromTemplate(null)}
        />
      )}

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
              <FormField label="Sources to search">
                {() => (
                  <SourceTypePicker
                    selected={form.sourceTypes}
                    onChange={(next) => update('sourceTypes', next)}
                    capabilities={capabilities}
                    numVideos={form.numVideos}
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
                label={isDefaultSourceTypes(form.sourceTypes) ? 'Number of videos' : 'Number of results'}
                helperText={`Your ${tier} plan allows up to ${numVideosCap} ${
                  isDefaultSourceTypes(form.sourceTypes) ? 'videos' : 'results, across all sources,'
                } per research run.`}
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

          {/* S-1.18.2: the R1 opt-in, measured before it was built (runs 1-8,
              docs/notes/2026-10-18-r1-visual-measurement.md). */}
          {featureFlags.visualAnalysis ? (
            <VisualAnalysisOption
              checked={form.visualAnalysis}
              onChange={(next) => update('visualAnalysis', next)}
              installEnabled={visualInstallEnabled}
              modelsAvailable={visualModelsAvailable}
            />
          ) : (
            form.visualAnalysis && (
              // D-105: hidden until the attribution guard lands; a run or
              // template that carried it over runs without it, and says so.
              <p
                data-testid="visual-analysis-paused"
                style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}
              >
                Visual analysis is paused in this version, so this run will go without frames.
              </p>
            )
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

          <div style={{ marginTop: space['2'], display: 'flex', gap: space['3'], alignItems: 'center', flexWrap: 'wrap' }}>
            <Button
              type="submit"
              disabled={submitDisabled}
              loading={createJob.isPending}
              title={topicBlocked ? FEATURE_UNAVAILABLE_MSG : undefined}
              style={{ minWidth: 160 }}
            >
              Begin research
            </Button>
            <Button
              type="button"
              variant="tertiary"
              onClick={() => {
                const result = formToTemplateParameters(form);
                if (!result.ok) {
                  setValidationError(result.error);
                  return;
                }
                setSavingTemplate(true);
              }}
            >
              Save as template
            </Button>
          </div>
        </form>
      </Card>

      <SaveTemplateModal
        open={savingTemplate}
        onClose={() => setSavingTemplate(false)}
        onSubmit={saveFormAsTemplate}
      />
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

function TemplateOriginBanner({
  origin,
  typeChanged,
  saving,
  onSaveChanges,
  onDetach,
}: {
  origin: TemplateOrigin;
  typeChanged: boolean;
  saving: boolean;
  onSaveChanges: () => void;
  onDetach: () => void;
}) {
  const c = useColors();
  return (
    <Card
      sunken
      style={{
        marginBottom: space['4'],
        padding: `${space['3']} ${space['4']}`,
        display: 'flex',
        flexDirection: 'column',
        gap: space['2'],
      }}
    >
      <div style={{ display: 'flex', gap: space['3'], alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, flex: '1 1 260px' }}>
          From {origin.builtin ? 'starter' : 'template'}{' '}
          <strong style={{ color: c.textPrimary, fontWeight: fontWeight.semibold }}>{origin.name}</strong>
          {!origin.builtin && <> · v{origin.version}</>}.{' '}
          {typeChanged
            ? 'You switched the research type, so this run will not be recorded as from the template.'
            : origin.jobType === 'topic'
              ? 'Type a topic; any other change applies to this run only.'
              : origin.needsChannels
                ? 'Add the channels; any other change applies to this run only.'
                : 'Any change applies to this run only.'}
        </span>
        {!origin.builtin && !typeChanged && (
          <Button size="sm" variant="secondary" type="button" onClick={onSaveChanges} loading={saving}>
            Save changes as v{origin.version + 1}
          </Button>
        )}
        <Button size="sm" variant="tertiary" type="button" onClick={onDetach}>
          Detach
        </Button>
      </div>
      {origin.problems.length > 0 && (
        <p role="alert" style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.warn }}>
          {origin.problems.join(' ')}
        </p>
      )}
    </Card>
  );
}
