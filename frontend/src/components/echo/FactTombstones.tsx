import { useClearFactTombstone, useFactTombstones } from '../../hooks/useEcho';
import { useJobStore } from '../../stores/jobStore';
import type { FactTombstone } from '../../services/echoApi';
import { Button, Card } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';
import { kindLabel } from '../../utils/echoReadiness';
import { formatDate } from '../../utils/formatters';
import { detailFromErrorBody, type HttpErrorLike } from '../../utils/ingestResults';

/** Whether a fact with this `source` was worked out by a connector or an
 * import, so deleting it records a tombstone (T-3.2.4.4). */
export function isDerivedSource(source: string | null | undefined): boolean {
  return !!source && (source.startsWith('connector:') || source.startsWith('import:'));
}

/** The line the delete dialogs add for a derived fact. */
export function keptDeletedNote(source: string | null | undefined): string | null {
  return isDerivedSource(source)
    ? 'Echo worked this out from a connector or an import, so it will keep it deleted: later syncs and re-imports skip it. You can allow it again under "Kept deleted".'
    : null;
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
    clear.mutate(t.id, {
      onSuccess: () => pushToast('success', clearedToast(t)),
      onError: (e) =>
        pushToast('error', detailFromErrorBody((e as HttpErrorLike).response?.data) ?? 'Could not allow it again.'),
    });

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
