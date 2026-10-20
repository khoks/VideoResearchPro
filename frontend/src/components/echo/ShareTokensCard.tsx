import { useState } from 'react';
import { useCreateShareToken, useRevokeShareToken, useShareTokens } from '../../hooks/useEcho';
import { useJobStore } from '../../stores/jobStore';
import api from '../../services/api';
import type { CreatedShareToken } from '../../services/echoApi';
import { Button, Card, Input, Skeleton } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { formatDate } from '../../utils/formatters';
import { apiOrigin, lastUsedLabel } from '../../utils/echoExtension';
import { detailFromErrorBody, type HttpErrorLike } from '../../utils/ingestResults';

/**
 * "Add from your browser" (S-3.7.3): share tokens for the Add to Echo
 * extension. A token can only add to the inbox; it is shown once, listed by
 * its first characters, and revoked here. The server address the extension
 * needs is shown beside it.
 */
export function ShareTokensCard() {
  const c = useColors();
  const pushToast = useJobStore((s) => s.pushToast);
  const tokens = useShareTokens();
  const create = useCreateShareToken();
  const revoke = useRevokeShareToken();
  const [label, setLabel] = useState('');
  const [fresh, setFresh] = useState<CreatedShareToken | null>(null);
  const server = apiOrigin(api.defaults.baseURL, window.location.origin);
  const items = tokens.data?.items ?? [];
  const atMax = tokens.data ? items.length >= tokens.data.max : false;

  const text: React.CSSProperties = { margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal };
  const mono: React.CSSProperties = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: fontSize.sm, color: c.textPrimary, overflowWrap: 'anywhere' };

  const copy = async (value: string, what: string) => {
    try {
      await navigator.clipboard.writeText(value);
      pushToast('success', `${what} copied.`);
    } catch {
      pushToast('error', 'Could not copy; select it and copy by hand.');
    }
  };

  const make = () =>
    create.mutate(label.trim() || 'Browser extension', {
      onSuccess: (t) => {
        setFresh(t);
        setLabel('');
      },
      onError: (err) => pushToast('error', detailFromErrorBody((err as HttpErrorLike).response?.data) ?? 'Could not make a token.'),
    });

  return (
    <Card>
      <h2 style={{ margin: `0 0 ${space['2']}`, fontFamily: fonts.display, fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
        Add from your browser
      </h2>
      <p style={text}>
        The Add to Echo extension sends a page, a link, a quote or an image to your inbox when you right-click it. It needs a share
        token: a key that can only add to Echo, never read from it. Load the extension from the <code>extension/</code> folder of
        Pratidhvani (Chrome: Extensions, Developer mode, Load unpacked), then paste the server address and a token into its settings.
      </p>

      <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap', margin: `${space['3']} 0` }}>
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>Server address</span>
        <span style={mono}>{server}</span>
        <Button size="sm" variant="tertiary" onClick={() => copy(server, 'Server address')}>
          Copy
        </Button>
      </div>

      {fresh && (
        <div
          role="status"
          style={{ border: `1px solid ${c.gold}`, borderRadius: radius.md, padding: space['3'], margin: `0 0 ${space['3']}`, display: 'flex', flexDirection: 'column', gap: space['2'] }}
        >
          <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
            Your new token for "{fresh.label}". Copy it now: it is not shown again.
          </span>
          <span style={mono}>{fresh.token}</span>
          <div style={{ display: 'flex', gap: space['2'] }}>
            <Button size="sm" onClick={() => copy(fresh.token, 'Token')}>
              Copy token
            </Button>
            <Button size="sm" variant="tertiary" onClick={() => setFresh(null)}>
              Done
            </Button>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ flex: '1 1 220px' }}>
          <Input
            value={label}
            maxLength={100}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Where it will live, e.g. Chrome on the work laptop"
            aria-label="Token label"
          />
        </div>
        <Button onClick={make} loading={create.isPending} disabled={atMax}>
          Make a share token
        </Button>
      </div>
      {atMax && (
        <p style={{ ...text, fontSize: fontSize.sm, marginTop: space['2'] }}>You have the most tokens allowed; revoke one to make another.</p>
      )}

      <div style={{ marginTop: space['3'], display: 'flex', flexDirection: 'column', gap: space['2'] }}>
        {tokens.isLoading ? (
          <Skeleton variant="row" />
        ) : items.length === 0 ? (
          <p style={{ ...text, color: c.textMuted }}>No share tokens yet.</p>
        ) : (
          items.map((t) => (
            <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.base, color: c.textPrimary }}>{t.label}</span>
              <span style={mono}>{t.prefix}…</span>
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>
                Made {formatDate(t.created_at)} · {lastUsedLabel(t.last_used_at)}
              </span>
              <Button
                size="sm"
                variant="tertiary"
                style={{ marginLeft: 'auto' }}
                loading={revoke.isPending && revoke.variables === t.id}
                onClick={() =>
                  revoke.mutate(t.id, {
                    onSuccess: () => pushToast('success', `Revoked "${t.label}". The extension using it stops working now.`),
                    onError: () => pushToast('error', 'Could not revoke it.'),
                  })
                }
              >
                Revoke
              </Button>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
