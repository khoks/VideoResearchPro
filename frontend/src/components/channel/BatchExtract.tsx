import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { knowledgeApi } from '../../services/knowledgeApi';
import { remainingQuota } from '../../services/quotaApi';
import type { DocumentRef } from '../../services/channelIntelligenceApi';
import { useQuota, intelligenceKey } from '../../hooks/useChannelIntelligence';
import { useFeatureAvailable } from '../../hooks/useFeatureAvailable';
import { planBatch, runBatch, type BatchProgress } from '../../utils/batchExtract';
import { Button } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';

const RESOURCE = 'knowledge_extractions';

/**
 * "Extract knowledge for all" (S-8.7.3). Runs the existing per-document
 * extraction one document at a time — each call is visibility-checked and
 * quota-metered server-side — never planning more than the reader has left
 * this month, stopping at the first quota refusal, and refreshing the
 * channel's aggregate when it ends. Runs in this tab: leaving the page stops
 * it after the current document.
 */
export function BatchExtract({ channelId, extractable }: { channelId: string; extractable: DocumentRef[] }) {
  const c = useColors();
  const qc = useQueryClient();
  const quota = useQuota();
  const llmUp = useFeatureAvailable('knowledge_extraction');
  const [confirming, setConfirming] = useState(false);
  const [progress, setProgress] = useState<BatchProgress | null>(null);
  const [running, setRunning] = useState(false);
  const stopRef = useRef(false);

  useEffect(() => () => {
    stopRef.current = true;
  }, []);

  const remaining = remainingQuota(quota.data, RESOURCE);
  const plan = planBatch(extractable, remaining);

  const start = async () => {
    setConfirming(false);
    setRunning(true);
    stopRef.current = false;
    await runBatch(plan, (id) => knowledgeApi.extract(id), {
      shouldStop: () => stopRef.current,
      onProgress: setProgress,
      statusOf: (err) => (isAxiosError(err) ? err.response?.status : undefined),
    });
    setRunning(false);
    void qc.invalidateQueries({ queryKey: intelligenceKey(channelId) });
    void qc.invalidateQueries({ queryKey: ['authQuota'] });
  };

  if (extractable.length === 0 && !progress) return null;

  const text = { fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, margin: 0 } as const;
  const remainingText = Number.isFinite(remaining) ? `${remaining} left this month` : 'no monthly limit on your plan';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'], marginTop: space['3'] }}>
      {running && progress ? (
        <>
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.done}
            aria-label="Knowledge reports made"
            style={{ height: 6, background: c.surfaceAlt, borderRadius: radius.pill, overflow: 'hidden' }}
          >
            <div style={{ height: '100%', width: `${(progress.done / Math.max(1, progress.total)) * 100}%`, background: c.accent }} />
          </div>
          <p style={text} aria-live="polite">
            {progress.done} of {progress.total}
            {progress.current ? ` · now: ${progress.current.title}` : ''}
          </p>
          <div>
            <Button size="sm" variant="secondary" onClick={() => (stopRef.current = true)}>
              Stop after this one
            </Button>
          </div>
        </>
      ) : confirming ? (
        <>
          <p style={text}>
            This makes <strong style={{ color: c.textPrimary }}>{plan.length}</strong> knowledge{' '}
            {plan.length === 1 ? 'report' : 'reports'}, one after another, about a minute each, and uses{' '}
            {plan.length} of your knowledge extractions ({remainingText}). Keep this page open; leaving it
            stops the run after the current document.
          </p>
          <div style={{ display: 'flex', gap: space['2'] }}>
            <Button size="sm" onClick={() => void start()}>
              Start
            </Button>
            <Button size="sm" variant="tertiary" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        </>
      ) : (
        <div style={{ display: 'flex', gap: space['3'], alignItems: 'center', flexWrap: 'wrap' }}>
          <Button
            size="sm"
            variant="secondary"
            disabled={plan.length === 0 || !llmUp || quota.isLoading}
            onClick={() => setConfirming(true)}
            title={!llmUp ? 'Knowledge extraction is temporarily unavailable' : undefined}
          >
            Extract knowledge for {plan.length} {plan.length === 1 ? 'document' : 'documents'}
          </Button>
          <span style={{ ...text, fontSize: fontSize.xs }}>
            {plan.length < extractable.length
              ? `${extractable.length} could be extracted; your plan has ${remainingText}.`
              : remainingText.charAt(0).toUpperCase() + remainingText.slice(1) + '.'}
          </span>
        </div>
      )}
      {!running && progress?.stoppedBy && (
        <p role="status" style={{ ...text, color: progress.stoppedBy === 'quota' ? c.warn : c.textSecondary, fontWeight: fontWeight.medium }}>
          {progress.stoppedBy === 'quota'
            ? `Stopped: your monthly knowledge extractions ran out after ${progress.made}.`
            : progress.stoppedBy === 'user'
              ? `Stopped after ${progress.made} ${progress.made === 1 ? 'report' : 'reports'}.`
              : `Made ${progress.made} ${progress.made === 1 ? 'report' : 'reports'}.`}
          {progress.skipped ? ` ${progress.skipped} skipped (no transcript, or already done).` : ''}
          {progress.failed ? ` ${progress.failed} failed; try those again later.` : ''}
        </p>
      )}
    </div>
  );
}
