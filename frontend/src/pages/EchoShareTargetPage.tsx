import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, Spinner } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { formatBytes } from '../utils/echoShares';
import {
  deliverPendingShares,
  discardPendingShares,
  readPendingShares,
  unsentParts,
  type PendingShare,
  type ShareDelivery,
  type SharePart,
} from '../services/shareTarget';
import { useJobStore } from '../stores/jobStore';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../theme';

type Stage =
  | { kind: 'reading' }
  | { kind: 'review'; items: PendingShare[] }
  | { kind: 'working' }
  | { kind: 'lost' }
  | Exclude<ShareDelivery, { kind: 'added' }>;

const PREVIEW_CHARS = 280;

function partLine(part: SharePart): string {
  if (part.kind === 'file') return `${part.file.name} (${formatBytes(part.file.size)})`;
  if (part.kind === 'url') return part.url;
  const text = part.text.trim();
  return text.length > PREVIEW_CHARS ? `${text.slice(0, PREVIEW_CHARS)}…` : text;
}

/**
 * Where a share from the Android share sheet lands (T-3.7.6.1). A signed-in
 * route, so signing in comes first and the share waits on the device. The
 * server's share intake decides who may add it.
 *
 * This is the one surface with a step of its own, and the step is the point.
 * The share target takes a form post, any website can make one, and the
 * worker cannot tell it from the share sheet, so a share that posted itself
 * would be a stranger's page acting with the user's session. Nothing leaves
 * this page without a tap, and the tap covers what was shown: a share that
 * arrives while this page is open waits for its own look.
 */
export function EchoShareTargetPage() {
  const c = useColors();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pushToast = useJobStore((s) => s.pushToast);
  const [params] = useSearchParams();
  const lost = params.get('failed') === '1';
  const [stage, setStage] = useState<Stage>(lost ? { kind: 'lost' } : { kind: 'reading' });
  const reviewed = useRef<string[]>([]);

  useEffect(() => {
    if (lost) return;
    let live = true;
    readPendingShares()
      .catch(() => [] as PendingShare[])
      .then((items) => {
        if (!live) return;
        reviewed.current = items.map((item) => item.key);
        setStage(items.length ? { kind: 'review', items } : { kind: 'nothing' });
      });
    return () => {
      live = false;
    };
  }, [lost]);

  const settle = useCallback(
    (outcome: ShareDelivery) => {
      if (outcome.kind !== 'nothing') void queryClient.invalidateQueries({ queryKey: ['echo', 'shares'] });
      if (outcome.kind !== 'added') {
        setStage(outcome);
        return;
      }
      pushToast('success', outcome.skipped ? `Added to Echo. Only the first files were kept; ${outcome.skipped} left out.` : 'Added to Echo.');
      navigate('/echo/inbox', { replace: true });
    },
    [navigate, pushToast, queryClient],
  );

  const add = useCallback(() => {
    setStage({ kind: 'working' });
    void deliverPendingShares(reviewed.current).then(settle);
  }, [settle]);

  const discard = useCallback(() => {
    void discardPendingShares(reviewed.current).finally(() => {
      pushToast('info', 'Discarded. Nothing was added.');
      navigate('/echo/inbox', { replace: true });
    });
  }, [navigate, pushToast]);

  const text: React.CSSProperties = { margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal };
  const inbox = <Link to="/echo/inbox" style={{ color: c.accent }}>your inbox</Link>;
  const actions = { display: 'flex', flexWrap: 'wrap' as const, gap: space['2'] };

  return (
    <div style={{ maxWidth: measure.reading, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: space['4'] }}>
      <h1 style={{ fontFamily: fonts.display, fontSize: fontSize['2xl'], fontWeight: fontWeight.semibold, color: c.textPrimary, margin: 0, lineHeight: lineHeight.tight }}>
        Add to Echo
      </h1>
      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          {stage.kind === 'reading' && <Spinner label="Reading what was shared" />}
          {stage.kind === 'working' && <Spinner label="Adding to Echo" />}
          {stage.kind === 'nothing' && <p style={text}>Nothing is waiting to be added. What you share lands in {inbox}.</p>}
          {stage.kind === 'lost' && <p style={text}>This device could not keep what you shared. Share it again, or add it from {inbox}.</p>}
          {stage.kind === 'review' && (
            <>
              <p style={text}>This was sent to Echo. Add it to {inbox}?</p>
              <ul style={{ margin: 0, paddingLeft: space['5'], display: 'flex', flexDirection: 'column', gap: space['2'] }}>
                {stage.items.flatMap((item) =>
                  unsentParts(item).parts.map((part, index) => (
                    <li key={`${item.key}#${index}`} style={{ ...text, color: c.textPrimary, overflowWrap: 'anywhere' }}>
                      {partLine(part)}
                    </li>
                  )),
                )}
              </ul>
              {stage.items.some((item) => unsentParts(item).skipped > 0) && <p style={text}>Only the first files are kept.</p>}
              <p style={text}>Any website can send something here. If you did not just share this, discard it.</p>
              <div style={actions}>
                <Button onClick={add}>Add to Echo</Button>
                <Button variant="secondary" onClick={discard}>Discard</Button>
              </div>
            </>
          )}
          {stage.kind === 'refused' && (
            <>
              <p role="alert" style={text}>{stage.detail ?? 'Echo would not take that.'}</p>
              {(stage.count > 0 || stage.refused > 1) && <p style={text}>{stage.count} added, {stage.refused} refused.</p>}
              {stage.status === 403 && <Link to="/account/subscription" style={{ color: c.accent, fontFamily: fonts.ui }}>See the plans</Link>}
            </>
          )}
          {stage.kind === 'failed' && (
            <>
              <p role="alert" style={text}>
                {stage.detail ?? 'Could not reach Echo.'} What you shared is still on this device.
              </p>
              <div style={actions}>
                <Button onClick={add}>Try again</Button>
                <Button variant="secondary" onClick={discard}>Discard</Button>
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}
