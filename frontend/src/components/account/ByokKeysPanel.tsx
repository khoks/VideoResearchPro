import { useState, type KeyboardEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useColors } from '../../hooks/useTheme';
import { useTierCapabilities } from '../../hooks/useTierCapabilities';
import { useJobStore } from '../../stores/jobStore';
import {
  CREDENTIALS_QUERY_KEY,
  credentialsApi,
  parseServerTime,
  type CredentialMetadata,
} from '../../services/credentialsApi';
import { apiErrorMessage } from '../../utils/apiError';
import { formatDate } from '../../utils/formatters';
import { Badge, Button, Card, FormField, Input, Modal, Skeleton } from '../primitives';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';

/**
 * "Your API keys" on /account/ai-models (E-5.6 BYOK).
 *
 * Studio only, like the API (`require_feature("byok_llm_keys")`): other tiers
 * see what the plan adds and never call `/auth/credentials`. A key is typed
 * into a password field, sent once in the PUT body, and the field is emptied
 * the moment Save is pressed; it never enters React Query (no mutation
 * variables), the toast, or the console. The server answers with metadata
 * only, so the panel can show whether a key is set and when it last changed,
 * never the key.
 *
 * `providers` comes from `GET /settings/llm` `byok.providers`: the providers
 * a stored key is actually used for (the local endpoint is not one).
 * `keysPersist` false means the install has no valid BYOK_ENCRYPTION_KEY;
 * `keyInvalid` tells "set but malformed" (no save can work, so saving is
 * off) apart from "unset" (saves work until the server restarts).
 */

const PROVIDER_NAMES: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  local: 'Local endpoint',
};

/** What an older API (no `byok` block) used a key for. */
const FALLBACK_PROVIDERS = ['anthropic', 'google', 'openai'];

export function providerName(provider: string): string {
  return PROVIDER_NAMES[provider] ?? provider;
}

export function ByokKeysPanel({
  providers,
  keysPersist,
  keyInvalid,
}: {
  providers?: string[];
  keysPersist?: boolean;
  keyInvalid?: boolean;
}) {
  const { has, isLoading: tierLoading } = useTierCapabilities();
  const allowed = has('byok_llm_keys');
  if (tierLoading) return <Skeleton variant="card" height={120} />;
  if (!allowed) return <LockedPanel />;
  return (
    <KeysPanel
      providers={providers ?? FALLBACK_PROVIDERS}
      keysPersist={keysPersist}
      keyInvalid={keyInvalid === true}
    />
  );
}

function PanelHeading({ children }: { children: ReactNode }) {
  const c = useColors();
  return (
    <h2
      style={{
        margin: 0,
        fontFamily: fonts.display,
        fontSize: fontSize.lg,
        fontWeight: fontWeight.semibold,
        color: c.textPrimary,
      }}
    >
      {children}
    </h2>
  );
}

function Prose({ children, muted = false }: { children: ReactNode; muted?: boolean }) {
  const c = useColors();
  return (
    <p
      style={{
        margin: 0,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        color: muted ? c.textMuted : c.textSecondary,
        lineHeight: lineHeight.normal,
        maxWidth: '75ch',
      }}
    >
      {children}
    </p>
  );
}

function LockedPanel() {
  const navigate = useNavigate();
  return (
    <Card data-byok-locked style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
        <PanelHeading>Your API keys</PanelHeading>
        <Badge tone="accent" size="sm">
          Studio
        </Badge>
      </div>
      <Prose>
        On the Studio plan you can add your own OpenAI, Anthropic or Google key. Your calls to
        that provider then use it, and bill to your own account, instead of the install's key.
      </Prose>
      <div>
        <Button variant="secondary" size="sm" onClick={() => navigate('/account/subscription')}>
          See plans
        </Button>
      </div>
    </Card>
  );
}

function Notice({ children, ...rest }: { children: ReactNode } & Record<`data-${string}`, boolean>) {
  const c = useColors();
  return (
    <div
      role="note"
      {...rest}
      style={{
        borderLeft: `3px solid ${c.warn}`,
        background: c.warnSubtle,
        borderRadius: radius.sm,
        padding: `${space['2']} ${space['3']}`,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        lineHeight: lineHeight.snug,
        color: c.textPrimary,
      }}
    >
      {children}
    </div>
  );
}

function KeysPanel({
  providers,
  keysPersist,
  keyInvalid,
}: {
  providers: string[];
  keysPersist?: boolean;
  keyInvalid: boolean;
}) {
  const c = useColors();
  const qc = useQueryClient();
  const pushToast = useJobStore((s) => s.pushToast);
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  const keys = useQuery({ queryKey: CREDENTIALS_QUERY_KEY, queryFn: credentialsApi.list });
  const stored = keys.data ?? [];
  const byProvider = new Map(stored.map((k) => [k.provider, k]));
  // A key stored for a provider no call reads (say, `local` through the API).
  const unused = stored.filter((k) => !providers.includes(k.provider));

  const remove = useMutation({
    mutationFn: (provider: string) => credentialsApi.remove(provider),
    onSuccess: (_data, provider) => {
      setRemoving(null);
      pushToast('success', `Removed your ${providerName(provider)} key.`);
      void qc.invalidateQueries({ queryKey: CREDENTIALS_QUERY_KEY });
    },
  });

  const onSaved = (provider: string) => {
    setEditing(null);
    pushToast('success', `Saved. Your calls to ${providerName(provider)} now use your key.`);
    void qc.invalidateQueries({ queryKey: CREDENTIALS_QUERY_KEY });
  };

  return (
    <Card flush data-byok-panel>
      <div
        style={{
          padding: `${space['4']} ${space['5']}`,
          borderBottom: `1px solid ${c.border}`,
          display: 'flex',
          flexDirection: 'column',
          gap: space['2'],
        }}
      >
        <PanelHeading>Your API keys</PanelHeading>
        <Prose>
          A key you add here is used for your own calls to that provider, in place of the
          install's key, and bills to your account. It is stored encrypted and never shown
          again, not even to you. Remove it to go back to the install's key.
        </Prose>
        {keyInvalid ? (
          <Notice data-byok-invalid>
            <span style={{ fontWeight: fontWeight.semibold }}>Keys cannot be saved right now.</span>{' '}
            This install's BYOK_ENCRYPTION_KEY is set but is not a valid key, so nothing can be
            encrypted: saving is turned off, and a key already stored here cannot be read, so your
            calls use the install's key. The operator must fix BYOK_ENCRYPTION_KEY. You can still
            remove a stored key.
          </Notice>
        ) : (
          keysPersist === false && (
            <Notice data-byok-ephemeral>
              <span style={{ fontWeight: fontWeight.semibold }}>Keys saved here do not last.</span>{' '}
              This install has no BYOK_ENCRYPTION_KEY, so a saved key is encrypted with a temporary
              key: it stops working when the server restarts, and background work (search and
              reports) cannot read it and uses the install's key instead. The operator can set
              BYOK_ENCRYPTION_KEY to make keys last.
            </Notice>
          )
        )}
      </div>

      {keys.isLoading && (
        <div style={{ padding: space['5'] }}>
          <Skeleton variant="card" height={96} />
        </div>
      )}

      {keys.isError && !keys.isLoading && (
        <div style={{ padding: `${space['4']} ${space['5']}`, display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          <Prose>{apiErrorMessage(keys.error, 'Your keys could not be loaded.')}</Prose>
          <div>
            <Button variant="secondary" size="sm" onClick={() => void keys.refetch()}>
              Try again
            </Button>
          </div>
        </div>
      )}

      {keys.isSuccess &&
        providers.map((provider, i) => (
          <ProviderRow
            key={provider}
            provider={provider}
            stored={byProvider.get(provider)}
            canSave={!keyInvalid}
            editing={editing === provider && !keyInvalid}
            onEdit={() => setEditing(provider)}
            onCancel={() => setEditing(null)}
            onSaved={() => onSaved(provider)}
            onRemove={() => setRemoving(provider)}
            isLast={i === providers.length - 1 && unused.length === 0}
          />
        ))}

      {keys.isSuccess &&
        unused.map((k, i) => (
          <UnusedRow
            key={k.provider}
            stored={k}
            onRemove={() => setRemoving(k.provider)}
            isLast={i === unused.length - 1}
          />
        ))}

      {!providers.includes('local') && (
        <div style={{ padding: `${space['3']} ${space['5']}`, borderTop: `1px solid ${c.border}` }}>
          <Prose muted>
            The local endpoint is the install's own server (LLM_LOCAL_BASE_URL), so it takes no
            key here.
          </Prose>
        </div>
      )}

      <Modal
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={removing ? `Remove your ${providerName(removing)} key?` : undefined}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRemoving(null)} disabled={remove.isPending}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={remove.isPending}
              onClick={() => removing && remove.mutate(removing)}
            >
              Remove key
            </Button>
          </>
        }
      >
        {removing && providers.includes(removing)
          ? `Your calls to ${providerName(removing)} go back to the install's key. You can add a key again at any time.`
          : 'No call uses this key, so removing it changes nothing else.'}
      </Modal>
    </Card>
  );
}

function rowStyle(borderColor: string, isLast: boolean) {
  return {
    padding: `${space['4']} ${space['5']}`,
    borderBottom: isLast ? 'none' : `1px solid ${borderColor}`,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: space['3'],
  };
}

function lastChanged(k: CredentialMetadata): string {
  return formatDate(parseServerTime(k.updated_at).toISOString());
}

function ProviderRow({
  provider,
  stored,
  canSave,
  editing,
  onEdit,
  onCancel,
  onSaved,
  onRemove,
  isLast,
}: {
  provider: string;
  stored: CredentialMetadata | undefined;
  canSave: boolean;
  editing: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSaved: () => void;
  onRemove: () => void;
  isLast: boolean;
}) {
  const c = useColors();
  const isSet = !!stored?.has_secret;
  return (
    <div data-byok-provider={provider} style={rowStyle(c.border, isLast)}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: space['3'] }}>
        <div style={{ flex: '1 1 220px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: space['1'] }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
            <span
              style={{
                fontFamily: fonts.ui,
                fontSize: fontSize.base,
                fontWeight: fontWeight.semibold,
                color: c.textPrimary,
              }}
            >
              {providerName(provider)}
            </span>
            <Badge tone={isSet ? 'success' : 'neutral'} size="sm">
              {isSet ? 'Key set' : 'Not set'}
            </Badge>
            {stored?.label && (
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
                {stored.label}
              </span>
            )}
          </div>
          <span data-byok-status style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
            {stored ? `Last changed ${lastChanged(stored)}` : "Your calls use the install's key."}
          </span>
        </div>
        {!editing && (
          <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap' }}>
            <Button variant="secondary" size="sm" onClick={onEdit} disabled={!canSave}>
              {isSet ? 'Replace key' : 'Add key'}
            </Button>
            {stored && (
              <Button variant="tertiary" size="sm" onClick={onRemove}>
                Remove
              </Button>
            )}
          </div>
        )}
      </div>
      {editing && (
        <KeyForm
          provider={provider}
          initialLabel={stored?.label ?? ''}
          replacing={isSet}
          onCancel={onCancel}
          onSaved={onSaved}
        />
      )}
    </div>
  );
}

function UnusedRow({
  stored,
  onRemove,
  isLast,
}: {
  stored: CredentialMetadata;
  onRemove: () => void;
  isLast: boolean;
}) {
  const c = useColors();
  return (
    <div data-byok-provider={stored.provider} style={rowStyle(c.border, isLast)}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: space['3'] }}>
        <div style={{ flex: '1 1 220px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: space['1'] }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
            <span style={{ fontFamily: fonts.ui, fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
              {providerName(stored.provider)}
            </span>
            <Badge tone="warn" size="sm">
              Not used
            </Badge>
          </div>
          <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
            A key is stored, but no call reads it. Last changed {lastChanged(stored)}.
          </span>
        </div>
        <Button variant="tertiary" size="sm" onClick={onRemove}>
          Remove
        </Button>
      </div>
    </div>
  );
}

/**
 * The key field. The draft lives here only until Save: the field is
 * emptied before the request goes out, and the key exists after that only
 * as the request body. A refused save shows the server's reason (which
 * never quotes the key) and leaves the field empty.
 *
 * Kept away from the browser's password manager, which would otherwise
 * offer to save the key as this site's password (and sync it, and autofill
 * it into the sign-in form). Chromium ignores `autocomplete="off"` on a
 * password field, and `new-password` is the sign-up signal that invites its
 * generator and its save prompt. So the field says `one-time-code`, which
 * Chromium's password manager leaves alone, and there is no <form>: Save is
 * a plain button and Enter is handled here, so no form submission happens
 * for submission detection to see.
 */
function KeyForm({
  provider,
  initialLabel,
  replacing,
  onCancel,
  onSaved,
}: {
  provider: string;
  initialLabel: string;
  replacing: boolean;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const c = useColors();
  const [draft, setDraft] = useState('');
  const [label, setLabel] = useState(initialLabel);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (saving) return;
    const secret = draft.trim();
    setDraft('');
    if (!secret) {
      setError('Paste a key first.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await credentialsApi.set(provider, secret, label.trim() || null);
      onSaved();
    } catch (err) {
      setError(apiErrorMessage(err, 'The key was not saved. Try again.'));
    } finally {
      setSaving(false);
    }
  };

  const onEnter = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter' || e.nativeEvent.isComposing) return;
    e.preventDefault();
    void submit();
  };

  const name = providerName(provider);
  return (
    <div
      role="group"
      data-byok-key-form
      aria-label={`${replacing ? 'Replace' : 'Add'} your ${name} key`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: space['3'],
        padding: space['4'],
        background: c.surfaceAlt,
        borderRadius: radius.md,
      }}
    >
      <FormField
        label={`${name} API key`}
        helperText={replacing ? 'The new key replaces the stored one.' : 'Sent once and stored encrypted.'}
        errorText={error ?? undefined}
      >
        {(id) => (
          <Input
            id={id}
            type="password"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onEnter}
            autoComplete="one-time-code"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            data-lpignore="true"
            data-1p-ignore="true"
            data-bwignore="true"
            data-form-type="other"
            invalid={!!error}
            disabled={saving}
            style={{ fontFamily: fonts.mono, fontSize: fontSize.sm }}
          />
        )}
      </FormField>
      <FormField label="Label" optional helperText="A note for you, such as which account the key is from.">
        {(id) => (
          <Input
            id={id}
            value={label}
            maxLength={128}
            onChange={(e) => setLabel(e.target.value)}
            onKeyDown={onEnter}
            disabled={saving}
            style={{ fontSize: fontSize.sm }}
          />
        )}
      </FormField>
      <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap' }}>
        <Button type="button" size="sm" loading={saving} onClick={() => void submit()}>
          Save key
        </Button>
        <Button type="button" variant="tertiary" size="sm" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
