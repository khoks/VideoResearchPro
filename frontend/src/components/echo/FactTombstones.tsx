import { useClearFactTombstone, useEchoContext, useFactTombstones } from '../../hooks/useEcho';
import { useJobStore } from '../../stores/jobStore';
import type { FactTombstone, PersonalContextItem } from '../../services/echoApi';
import { Button, Card } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';
import { kindLabel } from '../../utils/echoReadiness';
import { formatDate } from '../../utils/formatters';

/** Whether a fact with this `source` was worked out by a connector or an
 * import, so deleting it records a tombstone (T-3.2.4.4). */
export function isDerivedSource(source: string | null | undefined): boolean {
  return !!source && (source.startsWith('connector:') || source.startsWith('import:'));
}

/** The line the delete dialog adds when the row will appear under "Kept
 * deleted". The server says so (`kept_deleted_by`, T-3.2.1.14) with the answer
 * the delete itself uses, which `source` cannot: a row the user wrote says
 * `manual` and can still be wanted by a connector. */
export function keptDeletedNote(
  fact: Pick<PersonalContextItem, 'source' | 'kept_deleted_by'> | null | undefined,
): string | null {
  const by = fact?.kept_deleted_by;
  if (!by) return null;
  const why = isDerivedSource(fact.source)
    ? `Echo worked this out from ${by}, so it will keep it deleted`
    : `You wrote this, but ${by} works out the same entry, so Echo will keep it deleted`;
  return `${why}: later syncs and re-imports skip it. You can allow it again under "Kept deleted".`;
}

/** The same for revoking a whole source. A connector's rows all stay deleted;
 * of the `manual` source, only the rows a connector or an import wants do. */
export function revokedKeptNote(source: string | null | undefined, rows: PersonalContextItem[]): string | null {
  if (isDerivedSource(source)) {
    return 'A connected connector keeps running, but its syncs and re-imports skip these facts from now on (see "Kept deleted"). To stop it, disconnect it above.';
  }
  const kept = rows.filter((r) => r.source === source && r.kept_deleted_by).length;
  if (kept === 0) return null;
  return kept === 1
    ? 'One of them is also worked out by a connector or an import, so Echo will keep it deleted (see "Kept deleted").'
    : `${kept} of them are also worked out by a connector or an import, so Echo will keep those deleted (see "Kept deleted").`;
}

/** The rows a revoke will delete: the server's list for that source with the
 * expired ones in, which is what `revoke_source` takes. The page's own list leaves
 * them out by default, and an expired manual row can still be wanted (T-3.2.1.14). */
export function useRevokeScope(source: string | null) {
  return useEchoContext({ source: source ?? undefined, include_expired: true }, source !== null);
}

/** The revoke dialog's body. `listed` is the page's rows, used only until the
 * scope arrives, or if it cannot be read. */
export function RevokeSummary({ source, listed }: { source: string; listed: PersonalContextItem[] }) {
  const scope = useRevokeScope(source);
  const shown = listed.filter((r) => r.source === source).length;
  const count = scope.data?.length ?? shown;
  const note = revokedKeptNote(source, scope.data ?? listed);
  return (
    <>
      Every entry attributed to <strong>{source}</strong> ({count}
      {count > shown ? ', expired ones included' : ''}) will be deleted. This is the opt-out path for a connector; for
      manual entries it clears everything you typed under that source.
      {note ? ` ${note}` : ''}
    </>
  );
}

export function clearedToast(t: Pick<FactTombstone, 'key' | 'connector_display_name'>): string {
  return `Allowed again. ${t.connector_display_name} may bring “${t.key}” back at its next sync or import.`;
}

/**
 * T-3.2.4.4: derived facts the user deleted. A connector's sync or a
 * re-import would write them again; the server skips these keys until the
 * user clears one here. Hidden until there is something to show.
 */
export function FactTombstones({ enabled = true }: { enabled?: boolean }) {
  const c = useColors();
  const pushToast = useJobStore((s) => s.pushToast);
  const tombstones = useFactTombstones(enabled);
  const clear = useClearFactTombstone();
  const items = tombstones.data?.items ?? [];
  if (items.length === 0) return null;

  const allow = (t: FactTombstone) =>
    // A failure is said by the hook, once (T-3.4.1.17).
    clear.mutate(t.id, { onSuccess: () => pushToast('success', clearedToast(t)) });

  return (
    <details data-fact-tombstones style={{ marginTop: space['4'] }}>
      <summary style={{ cursor: 'pointer', fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.textSecondary }}>
        Kept deleted ({items.length})
      </summary>
      <p style={{ margin: `${space['2']} 0`, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textMuted, lineHeight: lineHeight.normal }}>
        Facts you deleted that a connector or an import worked out. Echo skips them on every sync and re-import. "Allow
        again" lets the next one bring a fact back if it still finds it.
      </p>
      <Card flush>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {items.map((t, i) => (
            <li
              key={t.id}
              data-fact-tombstone={t.id}
              style={{
                padding: `${space['2']} ${space['4']}`,
                display: 'flex',
                alignItems: 'baseline',
                gap: space['3'],
                flexWrap: 'wrap',
                borderBottom: i === items.length - 1 ? 'none' : `1px solid ${c.border}`,
              }}
            >
              <span style={{ flex: '1 1 12rem', minWidth: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, overflowWrap: 'anywhere' }}>
                {t.key}
              </span>
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
                {kindLabel(t.kind)} · from {t.connector_display_name} · deleted {formatDate(t.created_at)}
              </span>
              <Button size="sm" variant="tertiary" loading={clear.isPending && clear.variables === t.id} onClick={() => allow(t)}>
                Allow again
              </Button>
            </li>
          ))}
        </ul>
      </Card>
    </details>
  );
}
