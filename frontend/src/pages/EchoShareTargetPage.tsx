import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, Spinner } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { deliverPendingShares, type ShareDelivery } from '../services/shareTarget';
import { useJobStore } from '../stores/jobStore';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../theme';

type Stage = { kind: 'working' } | { kind: 'lost' } | Exclude<ShareDelivery, { kind: 'added' }>;

/**
 * Where a share from the Android share sheet lands (T-3.7.6.1). A signed-in
 * route, so signing in comes first and the share waits on the device. It is
 * added at once with no step of its own, like every surface, and the user
 * lands in the inbox. The server's share intake decides who may add it.
 */
export function EchoShareTargetPage() {
  const c = useColors();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pushToast = useJobStore((s) => s.pushToast);
  const [params] = useSearchParams();
  const lost = params.get('failed') === '1';
  const [stage, setStage] = useState<Stage>(lost ? { kind: 'lost' } : { kind: 'working' });
  const started = useRef(false);

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

  useEffect(() => {
    if (started.current || lost) return;
    started.current = true;
    void deliverPendingShares().then(settle);
  }, [settle, lost]);

  const text: React.CSSProperties = { margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal };
  const inbox = <Link to="/echo/inbox" style={{ color: c.accent }}>your inbox</Link>;

  return (
    <div style={{ maxWidth: measure.reading, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: space['4'] }}>
      <h1 style={{ fontFamily: fonts.display, fontSize: fontSize['2xl'], fontWeight: fontWeight.semibold, color: c.textPrimary, margin: 0, lineHeight: lineHeight.tight }}>
        Add to Echo
      </h1>
      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          {stage.kind === 'working' && <Spinner label="Adding to Echo" />}
          {stage.kind === 'nothing' && <p style={text}>Nothing is waiting to be added. What you share lands in {inbox}.</p>}
          {stage.kind === 'lost' && <p style={text}>This device could not keep what you shared. Share it again, or add it from {inbox}.</p>}
          {stage.kind === 'refused' && (
            <>
              <p role="alert" style={text}>
                {stage.detail ?? 'Echo would not take that.'}
                {stage.count > 0 ? ' The rest was added.' : ''}
              </p>
              {stage.status === 403 && <Link to="/account/subscription" style={{ color: c.accent, fontFamily: fonts.ui }}>See the plans</Link>}
            </>
          )}
          {stage.kind === 'failed' && (
            <>
              <p role="alert" style={text}>
                {stage.detail ?? 'Could not reach Echo.'} What you shared is still on this device.
              </p>
              <div>
                <Button
                  onClick={() => {
                    setStage({ kind: 'working' });
                    void deliverPendingShares().then(settle);
                  }}
                >
                  Try again
                </Button>
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}
