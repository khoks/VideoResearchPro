import { useState } from 'react';
import { useDeleteBrain, useEchoFootprint } from '../../hooks/useEcho';
import { useJobStore } from '../../stores/jobStore';
import { echoApi, type EchoFootprint } from '../../services/echoApi';
import { Button, Card, Input, Modal, Skeleton } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';
import { footprintTotal, isFootprintEmpty } from '../../utils/echoShares';
import { detailFromErrorBody, type HttpErrorLike } from '../../utils/ingestResults';

const TYPE_TO_CONFIRM = 'DELETE';

/**
 * "Your Echo data" (S-3.10.1 / S-3.10.2): export everything Echo holds as one
 * archive, see what it holds in each store, and delete all of it. The
 * footprint comes from the same count the server checks after a delete, so
 * "0 everywhere" here means the stores are empty, not that the UI forgot.
 */
export function EchoDataCard() {
  const c = useColors();
  const pushToast = useJobStore((s) => s.pushToast);
  const footprint = useEchoFootprint();
  const deleteBrain = useDeleteBrain();
  const [exporting, setExporting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState('');

  const doExport = async () => {
    setExporting(true);
    try {
      await echoApi.exportBrain();
    } catch {
      pushToast('error', 'Export failed. Nothing was changed; try again.');
    } finally {
      setExporting(false);
    }
  };

  const doDelete = () =>
    deleteBrain.mutate(undefined, {
      onSuccess: (resp) => {
        setConfirming(false);
        setTyped('');
        pushToast(
          'success',
          isFootprintEmpty(resp.footprint_after)
            ? 'Echo now holds nothing about you.'
            : 'Delete finished, but something was left; see the counts.',
        );
      },
      onError: (err) =>
        pushToast('error', detailFromErrorBody((err as HttpErrorLike).response?.data) ?? 'Delete failed. Nothing past the failing store was removed; try again.'),
    });

  const fp = footprint.data;
  const empty = fp ? isFootprintEmpty(fp) : false;
  const text: React.CSSProperties = { margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal };

  return (
    <Card>
      <h2 style={{ margin: `0 0 ${space['2']}`, fontFamily: fonts.display, fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
        Your Echo data
      </h2>
      <p style={text}>
        One archive holds every fact and share Echo keeps, with the files: a manifest, one JSON Lines file per table, and the
        files byte for byte. Your notes and the research library are not part of Echo and are not touched here.
      </p>

      <div style={{ margin: `${space['3']} 0` }}>
        {footprint.isLoading ? (
          <Skeleton variant="text" />
        ) : fp ? (
          <FootprintLine fp={fp} />
        ) : (
          <p style={{ ...text, color: c.textMuted }}>Couldn't read what Echo holds.</p>
        )}
      </div>

      <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap' }}>
        <Button variant="secondary" onClick={doExport} loading={exporting} disabled={empty}>
          Export everything
        </Button>
        <Button variant="danger" onClick={() => setConfirming(true)} disabled={empty}>
          Delete everything Echo knows
        </Button>
      </div>

      {confirming && fp && (
        <Modal
          open
          onClose={() => !deleteBrain.isPending && setConfirming(false)}
          title="Delete everything Echo knows?"
          disableBackdropClose
          footer={
            <>
              <Button variant="secondary" onClick={() => setConfirming(false)} disabled={deleteBrain.isPending}>
                Keep it
              </Button>
              <Button variant="danger" onClick={doDelete} loading={deleteBrain.isPending} disabled={typed !== TYPE_TO_CONFIRM}>
                Delete permanently
              </Button>
            </>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
            <p style={text}>
              This removes {footprintTotal(fp)} {footprintTotal(fp) === 1 ? 'item' : 'items'} from every place Echo keeps them:
              the facts and shares tables, the shared files, and the search vectors. There is no undo. Export first if you want a copy.
            </p>
            <FootprintLine fp={fp} />
            <label style={{ display: 'flex', flexDirection: 'column', gap: space['1'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
              Type {TYPE_TO_CONFIRM} to confirm
              <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus aria-label={`Type ${TYPE_TO_CONFIRM} to confirm`} />
            </label>
          </div>
        </Modal>
      )}
    </Card>
  );
}

function FootprintLine({ fp }: { fp: EchoFootprint }) {
  const c = useColors();
  const facts = fp.rows.personal_context ?? 0;
  const shares = fp.rows.shares_inbox ?? 0;
  const vectors = Object.values(fp.vectors).reduce((a, b) => a + b, 0);
  const parts = [
    `${facts} ${facts === 1 ? 'fact' : 'facts'}`,
    `${shares} ${shares === 1 ? 'share' : 'shares'}`,
    `${fp.files} ${fp.files === 1 ? 'file' : 'files'}`,
    `${vectors} search ${vectors === 1 ? 'vector' : 'vectors'}`,
  ];
  return (
    <p style={{ margin: 0, fontFamily: fonts.mono, fontSize: fontSize.xs, color: c.textSecondary }}>
      Echo holds: {parts.join(' · ')}
    </p>
  );
}
