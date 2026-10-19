import { useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useColors } from '../hooks/useTheme';
import { useOnboarding, useUpdateOnboarding } from '../hooks/useOnboarding';
import { useApproveJob, useCreateJob, useJob, useJobVideos } from '../hooks/useJobs';
import { useJobProgress } from '../hooks/useJobProgress';
import { useJobTemplates } from '../hooks/useJobTemplates';
import { Stepper } from '../components/onboarding/Stepper';
import { ProgressBar } from '../components/common/ProgressBar';
import { Button, Card, EmptyState, FormField, Input, Skeleton } from '../components/primitives';
import { validateChannels } from '../utils/jobForm';
import { apiErrorMessage } from '../utils/apiError';
import {
  FIRST_RUN_VIDEOS,
  MAX_ONBOARDING_CHANNELS,
  type Onboarding,
} from '../services/onboardingApi';
import type { JobCreate, JobProvenance } from '../types/job';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../theme';

/** The starter template the first run is created from (M6, S-8.6.x). */
export const FIRST_RUN_TEMPLATE_KEY = 'channel-deep-dive';

const STEPS = ['Choose channels', 'Start a small run', 'Read the report'];
type Step = 1 | 2 | 3;

/**
 * `/welcome` — the first-run wizard (S-8.10.1, plan docs/plans/m10-onboarding.md).
 *
 * A task flow with real actions, not an overlay tour: (1) the channels a
 * reader trusts; (2) a deliberately small channel run from the
 * "Channel deep-dive" starter, five videos so the transcript throttle does
 * not turn "see the result" into a long wait; (3) its progress, the approval
 * every run pauses for, and the report in the reader. Progress lives on the
 * server, so the wizard resumes on any device. Skip is always visible.
 */
export function WelcomePage() {
  const c = useColors();
  const navigate = useNavigate();
  const { data, isLoading, isError, refetch } = useOnboarding();
  const update = useUpdateOnboarding();
  // The reader's own navigation wins; until then, the step the server kept.
  const [chosenStep, setStep] = useState<Step | null>(null);
  const step: Step | null = chosenStep ?? data?.state.step ?? null;

  const goTo = (n: Step) => {
    setStep(n);
    update.mutate({ step: n });
  };

  const skip = async () => {
    if (data && !data.state.dismissed && !data.onboarded_at) {
      try {
        await update.mutateAsync({ dismissed: true });
      } catch {
        /* skipping must never trap the reader on this page */
      }
    }
    navigate('/submit');
  };

  if (isLoading) {
    return (
      <Shell onSkip={skip} skipLabel="Skip for now">
        <div aria-busy style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          <Skeleton variant="row" height={44} />
          <Skeleton variant="row" height={160} />
        </div>
      </Shell>
    );
  }

  if (isError || !data || step === null) {
    return (
      <Shell onSkip={skip} skipLabel="Skip for now">
        <EmptyState
          title="Couldn't load your progress."
          description="The wizard keeps its place on the server, and that request failed. Try again, or skip and explore on your own."
          action={
            <Button variant="secondary" onClick={() => void refetch()}>
              Retry
            </Button>
          }
        />
      </Shell>
    );
  }

  const finished = !!data.onboarded_at;
  const skipLabel = finished || data.state.dismissed ? 'Close' : 'Skip for now';

  return (
    <Shell onSkip={skip} skipLabel={skipLabel}>
      {finished && (
        <p style={{ ...noteStyle(c), marginTop: 0 }}>
          You finished this on {new Date(data.onboarded_at!).toLocaleDateString()}. It is here if you want to run it again.
        </p>
      )}
      <Stepper steps={STEPS} current={step} onSelect={(n) => goTo(n as Step)} />
      <div style={{ marginTop: space['5'] }}>
        {step === 1 && (
          <ChannelsStep
            initial={data.state.choices.channels}
            saving={update.isPending}
            onContinue={async (channels) => {
              // Wait for the save: step 2 reads the channels back from the server.
              await update.mutateAsync({ step: 2, channels });
              setStep(2);
            }}
          />
        )}
        {step === 2 && (
          <FirstRunStep
            data={data}
            onBack={() => goTo(1)}
            onStarted={async (jobId) => {
              await update.mutateAsync({ step: 3, first_job_id: jobId });
              setStep(3);
            }}
            onContinue={() => goTo(3)}
          />
        )}
        {step === 3 && (
          <ResultStep
            jobId={data.state.choices.first_job_id}
            onBack={() => goTo(2)}
            onDone={async (href) => {
              try {
                await update.mutateAsync({ completed: true });
              } catch {
                /* reading the report matters more than recording it */
              }
              navigate(href);
            }}
          />
        )}
      </div>
    </Shell>
  );
}

// ──────────────────────────────────────────────────────────────
// Step 1 — channels

function ChannelsStep({
  initial,
  saving,
  onContinue,
}: {
  initial: string[];
  saving: boolean;
  onContinue: (channels: string[]) => Promise<void>;
}) {
  const c = useColors();
  const [channels, setChannels] = useState<string[]>(initial);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const full = channels.length >= MAX_ONBOARDING_CHANNELS;

  const add = (e: FormEvent) => {
    e.preventDefault();
    const value = draft.trim();
    if (!value) return;
    if (validateChannels([value]).length > 0) {
      setError('That does not look like a YouTube channel. Paste a youtube.com/@name link, an @handle or a channel id starting UC.');
      return;
    }
    if (channels.includes(value)) {
      setError('That channel is already on the list.');
      return;
    }
    setChannels((list) => [...list, value]);
    setDraft('');
    setError(null);
    inputRef.current?.focus();
  };

  return (
    <StepCard
      title="Choose channels you trust"
      lede="Pratidhvani is curated, not balanced: it reads the sources you pick and nothing else. Add one to five YouTube channels. Your first run reads one of them, so it finishes quickly."
    >
      <form onSubmit={add} style={{ display: 'flex', gap: space['2'], alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 260px' }}>
          <FormField
            label="Channel link or handle"
            helperText={full ? `That is the most this step keeps (${MAX_ONBOARDING_CHANNELS}).` : 'For example @3blue1brown or youtube.com/@veritasium'}
            errorText={error ?? undefined}
          >
            {(id) => (
            <Input
              id={id}
              aria-describedby={`${id}-desc`}
              ref={inputRef}
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                if (error) setError(null);
              }}
              placeholder="@channel"
              disabled={full}
              invalid={!!error}
              autoComplete="off"
              spellCheck={false}
            />
            )}
          </FormField>
        </div>
        <Button type="submit" variant="secondary" disabled={full || !draft.trim()} style={{ minHeight: 44 }}>
          Add
        </Button>
      </form>

      {channels.length > 0 && (
        <ul aria-label="Chosen channels" style={{ listStyle: 'none', margin: `${space['4']} 0 0`, padding: 0, display: 'flex', flexWrap: 'wrap', gap: space['2'] }}>
          {channels.map((ch) => (
            <li
              key={ch}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: space['1'],
                padding: `0 ${space['1']} 0 ${space['3']}`,
                borderRadius: radius.pill,
                background: c.surfaceAlt,
                border: `1px solid ${c.border}`,
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                color: c.textPrimary,
                maxWidth: '100%',
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ch}</span>
              <button
                type="button"
                aria-label={`Remove ${ch}`}
                onClick={() => setChannels((list) => list.filter((x) => x !== ch))}
                style={{
                  minWidth: 32,
                  minHeight: 32,
                  border: 'none',
                  background: 'none',
                  color: c.textMuted,
                  cursor: 'pointer',
                  fontSize: fontSize.base,
                }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      {saveError && (
        <p role="alert" style={{ ...noteStyle(c), color: c.error }}>
          {saveError}
        </p>
      )}
      <Actions>
        <Button
          onClick={() => {
            setSaveError(null);
            onContinue(channels).catch((err) => setSaveError(apiErrorMessage(err, 'Your channels could not be saved. Try again.')));
          }}
          disabled={channels.length === 0}
          loading={saving}
        >
          Continue
        </Button>
      </Actions>
    </StepCard>
  );
}

// ──────────────────────────────────────────────────────────────
// Step 2 — the first run

const RETRYABLE = new Set(['failed', 'cancelled']);

function FirstRunStep({
  data,
  onBack,
  onStarted,
  onContinue,
}: {
  data: Onboarding;
  onBack: () => void;
  onStarted: (jobId: string) => Promise<void>;
  onContinue: () => void;
}) {
  const c = useColors();
  const channels = data.state.choices.channels;
  const [picked, setChosen] = useState<string | null>(null);
  const chosen = picked && channels.includes(picked) ? picked : channels[0] ?? '';
  const [error, setError] = useState<string | null>(null);
  const templates = useJobTemplates();
  const createJob = useCreateJob();

  const existing = data.state.choices.first_job_id ? data.milestones.first_job : null;
  const underWay = existing && existing.id === data.state.choices.first_job_id && !RETRYABLE.has(existing.status);

  if (channels.length === 0) {
    return (
      <StepCard title="Start a small run" lede="The first run needs a channel to read.">
        <Actions>
          <Button onClick={onBack}>Choose a channel</Button>
        </Actions>
      </StepCard>
    );
  }

  if (underWay) {
    return (
      <StepCard title="Your first run is under way" lede="It keeps going while you are away. Carry on to watch it, or come back later; this page remembers where you were.">
        <Actions>
          <Button variant="tertiary" onClick={onBack}>Back</Button>
          <Button onClick={onContinue}>See its progress</Button>
        </Actions>
      </StepCard>
    );
  }

  const start = async () => {
    setError(null);
    const starter = templates.data?.find((t) => t.builtin_key === FIRST_RUN_TEMPLATE_KEY);
    const body: JobCreate = {
      job_type: 'channel',
      channel_list: [chosen],
      videos_per_channel: FIRST_RUN_VIDEOS,
      num_videos: FIRST_RUN_VIDEOS,
    };
    const p = starter?.parameters;
    if (p?.min_duration_minutes != null) body.min_duration_minutes = p.min_duration_minutes;
    if (p?.max_duration_minutes != null) body.max_duration_minutes = p.max_duration_minutes;
    if (p?.output_length && p.output_length !== 'auto') body.output_length = p.output_length;
    const provenance: JobProvenance | undefined = starter
      ? { templateId: starter.id, templateVersion: starter.version }
      : undefined;
    try {
      const job = await createJob.mutateAsync({ data: body, provenance });
      await onStarted(job.id);
    } catch (err) {
      setError(apiErrorMessage(err, 'The run could not be started. Check the channel and try again.'));
    }
  };

  return (
    <StepCard
      title="Start a small run"
      lede={`Pratidhvani reads the ${FIRST_RUN_VIDEOS} most recent videos from one channel, indexes every line, and writes a report you can question, with each claim linked to the moment it was said.`}
    >
      {existing && RETRYABLE.has(existing.status) && (
        <p role="status" style={{ ...noteStyle(c), color: c.error }}>
          The last attempt did not finish. Try the same channel again or pick another.
        </p>
      )}
      <fieldset style={{ border: 'none', margin: 0, padding: 0 }}>
        <legend style={{ ...labelStyle(c), marginBottom: space['2'] }}>Which channel first?</legend>
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['1'] }}>
          {channels.map((ch) => (
            <label
              key={ch}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: space['2'],
                minHeight: 44,
                fontFamily: fonts.ui,
                fontSize: fontSize.base,
                color: c.textPrimary,
                cursor: 'pointer',
              }}
            >
              <input
                type="radio"
                name="first-channel"
                value={ch}
                checked={chosen === ch}
                onChange={() => setChosen(ch)}
                style={{ width: 18, height: 18, accentColor: c.accent }}
              />
              <span style={{ overflowWrap: 'anywhere' }}>{ch}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <Card sunken style={{ marginTop: space['4'] }}>
        <p style={{ ...noteStyle(c), margin: 0 }}>
          <strong style={{ color: c.textPrimary }}>How long it takes.</strong> Usually a few minutes. Transcripts are
          fetched a few seconds apart so YouTube does not block the server, and a video without captions is transcribed
          from its audio, which takes longer. The run pauses once so you can approve the videos it found.
        </p>
      </Card>

      {error && (
        <p role="alert" style={{ ...noteStyle(c), color: c.error }}>
          {error}
        </p>
      )}

      <Actions>
        <Button variant="tertiary" onClick={onBack}>Back</Button>
        <Button onClick={() => void start()} loading={createJob.isPending} disabled={!chosen || templates.isLoading}>
          Start the run
        </Button>
      </Actions>
    </StepCard>
  );
}

// ──────────────────────────────────────────────────────────────
// Step 3 — progress, approval, the report

const STATUS_COPY: Record<string, string> = {
  pending: 'Queued. It starts in a moment.',
  searching: "Finding the channel's latest videos.",
  extracting: 'Fetching transcripts, a few seconds apart.',
  building_rag: 'Indexing every line so it can be cited.',
  generating_report: 'Writing the report.',
};

function ResultStep({
  jobId,
  onBack,
  onDone,
}: {
  jobId: string | null;
  onBack: () => void;
  /** Finish the wizard, then go to `href` (the report, or the run without one). */
  onDone: (href: string) => Promise<void>;
}) {
  const c = useColors();
  const job = useJob(jobId);
  useJobProgress(jobId);
  const status = job.data?.status;
  const videos = useJobVideos(status === 'awaiting_approval' ? jobId : null);
  const approve = useApproveJob();
  const [reading, setReading] = useState(false);

  if (!jobId) {
    return (
      <StepCard title="Read the report" lede="Start a run first; its report appears here.">
        <Actions>
          <Button onClick={onBack}>Start a run</Button>
        </Actions>
      </StepCard>
    );
  }

  if (job.isLoading || !job.data) {
    return (
      <StepCard title="Read the report">
        <Skeleton variant="row" height={64} />
      </StepCard>
    );
  }

  const j = job.data;
  const runLink = (
    <Link to={`/jobs/${j.id}`} style={{ color: c.accent }}>
      the run&rsquo;s own page
    </Link>
  );

  if (j.status === 'awaiting_approval') {
    const list = videos.data ?? [];
    const ids = list.map((v) => v.video_id ?? v.document_id);
    return (
      <StepCard
        title="Approve what it found"
        lede="Every run pauses here so nothing enters your library without your say. These are the videos it found; approve them to continue."
      >
        {videos.isLoading ? (
          <Skeleton variant="row" height={88} />
        ) : (
          <ol style={{ margin: 0, paddingLeft: space['5'], display: 'flex', flexDirection: 'column', gap: space['1'] }}>
            {list.map((v) => (
              <li key={v.id} style={{ fontFamily: fonts.body, fontSize: fontSize.base, color: c.textPrimary, lineHeight: lineHeight.snug }}>
                {v.title}
              </li>
            ))}
          </ol>
        )}
        {approve.isError && (
          <p role="alert" style={{ ...noteStyle(c), color: c.error }}>
            {apiErrorMessage(approve.error, 'The approval did not go through. Try again.')}
          </p>
        )}
        <p style={noteStyle(c)}>To pick only some of them, use {runLink}.</p>
        <Actions>
          <Button
            onClick={() => approve.mutate({ id: j.id, data: { approved_video_ids: ids } })}
            loading={approve.isPending}
            disabled={ids.length === 0}
          >
            {ids.length === 1 ? 'Approve this video' : `Approve these ${ids.length} videos`}
          </Button>
        </Actions>
      </StepCard>
    );
  }

  if (j.status === 'completed') {
    if (!j.has_report) {
      return (
        <StepCard title="The run finished" lede="It finished without a report this time. Its sources are in your library, and you can still ask them questions.">
          <Actions>
            <Button variant="tertiary" onClick={onBack}>Try another run</Button>
            <Button onClick={() => void onDone(`/jobs/${j.id}`)}>Open the run</Button>
          </Actions>
        </StepCard>
      );
    }
    const sources = j.transcript_count || j.video_count;
    return (
      <StepCard
        title="Your report is ready"
        lede={`It draws on ${sources} ${sources === 1 ? 'video' : 'videos'}. Every citation opens the moment it came from. Afterwards, ask the run questions from its page.`}
      >
        <Actions>
          <Button
            loading={reading}
            onClick={() => {
              setReading(true);
              void onDone(`/reports/${j.id}`).finally(() => setReading(false));
            }}
          >
            Read the report
          </Button>
        </Actions>
      </StepCard>
    );
  }

  if (RETRYABLE.has(j.status)) {
    return (
      <StepCard title="The run did not finish" lede={j.error_message ?? 'Something stopped it before the report was written.'}>
        <Actions>
          <Button onClick={onBack}>Try again</Button>
        </Actions>
      </StepCard>
    );
  }

  const pct = Math.round(j.progress_pct ?? 0);
  return (
    <StepCard title="It is reading" lede="You can leave this page; the run keeps going, and this step picks up where it is when you come back.">
      <div
        role="progressbar"
        aria-label="First run progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        style={{ marginTop: space['2'] }}
      >
        <ProgressBar value={pct} />
      </div>
      <p aria-live="polite" style={noteStyle(c)}>
        {j.progress_message || STATUS_COPY[j.status] || 'Working.'}
      </p>
      <p style={noteStyle(c)}>Details, including each video as it lands, are on {runLink}.</p>
    </StepCard>
  );
}

// ──────────────────────────────────────────────────────────────
// Chrome

function Shell({ children, onSkip, skipLabel }: { children: ReactNode; onSkip: () => void; skipLabel: string }) {
  const c = useColors();
  return (
    <div style={{ maxWidth: '720px', margin: '0 auto' }}>
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: space['4'],
          marginBottom: space['5'],
          flexWrap: 'wrap',
        }}
      >
        <div style={{ minWidth: 0, flex: '1 1 320px' }}>
          <p style={{ ...labelStyle(c), margin: 0, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Getting started</p>
          <h1
            style={{
              fontFamily: fonts.display,
              fontSize: fontSize['2xl'],
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
              margin: `${space['1']} 0 0`,
              lineHeight: lineHeight.tight,
            }}
          >
            Your first report, in three steps
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
            Choose voices you trust, let Pratidhvani read a few of their videos, then read what they said.
          </p>
        </div>
        <Button variant="tertiary" onClick={onSkip} style={{ minHeight: 44 }}>
          {skipLabel}
        </Button>
      </header>
      {children}
    </div>
  );
}

function StepCard({ title, lede, children }: { title: string; lede?: string; children?: ReactNode }) {
  const c = useColors();
  return (
    <Card>
      <section aria-labelledby="welcome-step-title">
        <h2
          id="welcome-step-title"
          tabIndex={-1}
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize.xl,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            margin: 0,
            lineHeight: lineHeight.tight,
          }}
        >
          {title}
        </h2>
        {lede && (
          <p style={{ fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal, margin: `${space['2']} 0 ${space['4']}`, maxWidth: measure.reading }}>
            {lede}
          </p>
        )}
        {children}
      </section>
    </Card>
  );
}

function Actions({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: space['2'], marginTop: space['5'], flexWrap: 'wrap' }}>
      {children}
    </div>
  );
}

function noteStyle(c: ReturnType<typeof useColors>): CSSProperties {
  return {
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    color: c.textSecondary,
    lineHeight: lineHeight.normal,
    margin: `${space['3']} 0 0`,
  };
}

function labelStyle(c: ReturnType<typeof useColors>): CSSProperties {
  return {
    fontFamily: fonts.ui,
    fontSize: fontSize.xs,
    fontWeight: fontWeight.medium,
    color: c.textMuted,
  };
}
