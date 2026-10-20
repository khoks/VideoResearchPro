/**
 * Echo's connectors (S-3.2.1): what each one reads, connect through a consent
 * screen that shows the disclosure before any redirect, sync now, and
 * disconnect, which deletes everything the connector brought in.
 */
import { useState, type CSSProperties } from 'react';
import { Badge, Button, EmptyState, Modal } from '../primitives';
import { useRevokeConnector, useSyncConnector } from '../../hooks/useEcho';
import { useColors } from '../../hooks/useTheme';
import { echoApi, type ConnectorItem, type PrivacyWeight } from '../../services/echoApi';
import { apiErrorMessage } from '../../utils/apiError';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';

const WEIGHT: Record<PrivacyWeight, { label: string; tone: 'neutral' | 'info' | 'warn' | 'error' }> = {
  low: { label: 'Low privacy weight', tone: 'neutral' },
  medium: { label: 'Medium privacy weight', tone: 'info' },
  high: { label: 'High privacy weight', tone: 'warn' },
  very_high: { label: 'Very high privacy weight', tone: 'error' },
};

/** "pushed_commit" → "Pushed commit". */
export function humanize(eventType: string): string {
  const words = eventType.replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function when(iso: string | null): string {
  if (!iso) return 'never';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function ConsentDialog({
  connector,
  open,
  onClose,
}: {
  connector: ConnectorItem;
  open: boolean;
  onClose: () => void;
}) {
  const c = useColors();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const weight = WEIGHT[connector.privacy_weight] ?? WEIGHT.medium;

  const proceed = async () => {
    setBusy(true);
    setError(null);
    try {
      const { authorize_url } = await echoApi.authorizeConnector(connector.name, connector.consent_version);
      window.location.assign(authorize_url);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not start connecting. Try again.'));
      setBusy(false);
    }
  };

  const text: CSSProperties = { fontFamily: fonts.body, fontSize: fontSize.base, lineHeight: lineHeight.normal, color: c.textPrimary };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Connect ${connector.display_name}`}
      footer={
        <>
          <Button variant="tertiary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={proceed} loading={busy}>
            Continue to {connector.display_name}
          </Button>
        </>
      }
    >
      <div data-consent-dialog="" style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        <div>
          <Badge tone={weight.tone} size="sm">
            {weight.label}
          </Badge>
        </div>
        <p style={{ ...text, margin: 0, whiteSpace: 'pre-line' }}>{connector.consent_disclosure}</p>
        <div>
          <p style={{ margin: `0 0 ${space['1']}`, fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.textSecondary }}>
            What it records
          </p>
          <ul style={{ margin: 0, paddingLeft: space['5'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textPrimary }}>
            {connector.event_types.map((t) => (
              <li key={t}>{humanize(t)}</li>
            ))}
          </ul>
        </div>
        <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
          You can disconnect at any time. Disconnecting deletes everything this connector brought in. Your Echo export
          includes what it recorded, never its access token.
        </p>
        {error && (
          <p role="alert" style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error }}>
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}

function ConnectorRow({ connector }: { connector: ConnectorItem }) {
  const c = useColors();
  const [consenting, setConsenting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const sync = useSyncConnector();
  const revoke = useRevokeConnector();
  const grant = connector.grant;
  const weight = WEIGHT[connector.privacy_weight] ?? WEIGHT.medium;
  const meta: CSSProperties = { margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary };

  let status: string;
  if (!connector.configured && !grant) status = 'Not set up on this install.';
  else if (!grant) status = 'Not connected.';
  else if (grant.status === 'syncing') status = `Connected as ${grant.account_label ?? 'you'} · syncing…`;
  else status = `Connected as ${grant.account_label ?? 'you'} · ${grant.events} ${grant.events === 1 ? 'event' : 'events'} · last synced ${when(grant.last_sync_at)}`;

  return (
    <li
      data-connector={connector.name}
      style={{
        listStyle: 'none',
        padding: space['3'],
        border: `1px solid ${c.border}`,
        borderRadius: radius.md,
        display: 'flex',
        flexDirection: 'column',
        gap: space['2'],
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
          <span style={{ fontFamily: fonts.ui, fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
            {connector.display_name}
          </span>
          <Badge tone={weight.tone} size="sm">
            {weight.label}
          </Badge>
        </div>
        <div style={{ display: 'flex', gap: space['2'] }}>
          {grant ? (
            <>
              <Button size="sm" variant="secondary" onClick={() => sync.mutate(connector.name)} loading={sync.isPending}>
                Sync now
              </Button>
              <Button size="sm" variant="tertiary" onClick={() => setConfirming(true)}>
                Disconnect
              </Button>
            </>
          ) : (
            <Button size="sm" onClick={() => setConsenting(true)} disabled={!connector.configured}>
              Connect
            </Button>
          )}
        </div>
      </div>
      <p style={meta}>{status}</p>
      {grant?.last_error && (
        <p role="status" style={{ ...meta, color: c.error }}>
          {grant.last_error}{' '}
          {grant.last_error.startsWith('Reconnect') && (
            <Button size="sm" variant="tertiary" onClick={() => setConsenting(true)}>
              Reconnect
            </Button>
          )}
        </p>
      )}
      {grant?.consent_outdated && (
        <p style={meta}>
          What this connector reads has changed since you agreed.{' '}
          <Button size="sm" variant="tertiary" onClick={() => setConsenting(true)}>
            Review and reconnect
          </Button>
        </p>
      )}

      <ConsentDialog connector={connector} open={consenting} onClose={() => setConsenting(false)} />
      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title={`Disconnect ${connector.display_name}?`}
        footer={
          <>
            <Button variant="tertiary" onClick={() => setConfirming(false)} disabled={revoke.isPending}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={revoke.isPending}
              onClick={async () => {
                await revoke.mutateAsync(connector.name);
                setConfirming(false);
              }}
            >
              Disconnect and delete
            </Button>
          </>
        }
      >
        <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textPrimary }}>
          This deletes the {grant?.events ?? 0} {grant?.events === 1 ? 'event' : 'events'} {connector.display_name} brought in,
          the facts Echo inferred from them, and the stored access. Echo also asks {connector.display_name} to revoke the
          access; you can check that in your {connector.display_name} settings.
        </p>
      </Modal>
    </li>
  );
}

export function ConnectorsPanel({ connectors }: { connectors: ConnectorItem[] }) {
  if (connectors.length === 0) {
    return (
      <EmptyState
        size="sm"
        title="No connectors on this install."
        description="Until one is set up, everything Echo knows is what you write and share here."
      />
    );
  }
  return (
    <ul data-connectors-panel="" style={{ margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: space['3'] }}>
      {connectors.map((c) => (
        <ConnectorRow key={c.name} connector={c} />
      ))}
    </ul>
  );
}
