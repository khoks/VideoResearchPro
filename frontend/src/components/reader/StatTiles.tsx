/**
 * Small figure tiles under a reader title: corpus statistics for a report,
 * extraction counts for a knowledge artifact, chapters for a book.
 */
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../../theme';

export interface StatTile {
  label: string;
  value: number | null | undefined;
}

export function StatTiles({ tiles, label }: { tiles: StatTile[]; label: string }) {
  const c = useColors();
  const shown = tiles.filter((t): t is { label: string; value: number } => t.value != null);
  if (shown.length === 0) return null;
  return (
    <dl
      aria-label={label}
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: space['3'],
        margin: `0 0 ${space['6']}`,
        maxWidth: measure.reading,
      }}
    >
      {shown.map((t) => (
        <div
          key={t.label}
          style={{
            flex: '1 1 120px',
            padding: `${space['2']} ${space['3']}`,
            background: c.surfaceAlt,
            borderRadius: radius.md,
            fontFamily: fonts.ui,
          }}
        >
          <dt
            style={{
              fontSize: fontSize.xs,
              fontWeight: fontWeight.medium,
              color: c.textMuted,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
            }}
          >
            {t.label}
          </dt>
          <dd
            style={{
              margin: 0,
              fontFamily: fonts.display,
              fontSize: fontSize.lg,
              fontWeight: fontWeight.semibold,
              lineHeight: lineHeight.tight,
              color: c.textPrimary,
            }}
          >
            {t.value.toLocaleString()}
          </dd>
        </div>
      ))}
    </dl>
  );
}
