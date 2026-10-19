import type { CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import type { Shelf } from '../../services/shelvesApi';
import { useJobShelves } from '../../hooks/useShelves';
import { usePaletteColor } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';

interface ShelfChipProps {
  shelf: Pick<Shelf, 'id' | 'name' | 'color'>;
  /** Link to the shelf page. Pass `false` on the shelf page itself. */
  linked?: boolean;
  /** Renders a small × that calls back; the chip never removes anything itself. */
  onRemove?: () => void;
  removeBusy?: boolean;
  style?: CSSProperties;
}

/**
 * A bordered pill in the shelf's palette colour with the name always
 * present — colour is a hint, never the only signal (M1 plan).
 */
export function ShelfChip({ shelf, linked = true, onRemove, removeBusy, style }: ShelfChipProps) {
  const p = usePaletteColor(shelf.color);
  const base: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: space['1'],
    padding: `2px ${space['2']}`,
    borderRadius: radius.pill,
    background: p.bg,
    color: p.fg,
    border: `1px solid ${p.fg}`,
    fontFamily: fonts.ui,
    fontSize: fontSize.xs,
    fontWeight: fontWeight.medium,
    lineHeight: 1.4,
    maxWidth: 260,
    ...style,
  };
  const label = (
    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
      {shelf.name}
    </span>
  );
  return (
    <span style={base}>
      {linked ? (
        <Link
          to={`/shelves/${shelf.id}`}
          onClick={(e) => e.stopPropagation()}
          title={`Open shelf ${shelf.name}`}
          style={{ color: 'inherit', textDecoration: 'none', minWidth: 0, display: 'inline-flex' }}
        >
          {label}
        </Link>
      ) : (
        label
      )}
      {onRemove && (
        <button
          type="button"
          aria-label={`Remove from ${shelf.name}`}
          disabled={removeBusy}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          style={{
            background: 'transparent',
            border: 'none',
            padding: 0,
            marginLeft: 2,
            color: 'inherit',
            cursor: removeBusy ? 'wait' : 'pointer',
            fontSize: fontSize.sm,
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </span>
  );
}

/** The chips for every shelf a job sits on; renders nothing when there are none. */
export function JobShelfChips({ jobId, style }: { jobId: string; style?: CSSProperties }) {
  const { data } = useJobShelves(jobId);
  if (!data || data.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['1'], ...style }}>
      {data.map((shelf) => (
        <ShelfChip key={shelf.id} shelf={shelf} />
      ))}
    </div>
  );
}
