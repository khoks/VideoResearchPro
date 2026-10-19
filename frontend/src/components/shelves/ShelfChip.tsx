import type { CSSProperties } from 'react';
import type { Shelf } from '../../services/shelvesApi';
import { useJobShelves } from '../../hooks/useShelves';
import { LabelPill } from '../primitives';
import { space } from '../../theme';

interface ShelfChipProps {
  shelf: Pick<Shelf, 'id' | 'name' | 'color'>;
  /** Link to the shelf page. Pass `false` on the shelf page itself. */
  linked?: boolean;
  onRemove?: () => void;
  removeBusy?: boolean;
  style?: CSSProperties;
}

export function ShelfChip({ shelf, linked = true, onRemove, removeBusy, style }: ShelfChipProps) {
  return (
    <LabelPill
      color={shelf.color}
      to={linked ? `/shelves/${shelf.id}` : undefined}
      title={`Open shelf ${shelf.name}`}
      onRemove={onRemove}
      removeLabel={`Remove from ${shelf.name}`}
      removeBusy={removeBusy}
      style={style}
    >
      {shelf.name}
    </LabelPill>
  );
}

/** The chips for every shelf a job sits on; renders nothing when there are none. */
export function JobShelfChips({ jobId, style }: { jobId: string; style?: CSSProperties }) {
  const { shelves } = useJobShelves(jobId);
  if (shelves.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['1'], ...style }}>
      {shelves.map((shelf) => (
        <ShelfChip key={shelf.id} shelf={shelf} />
      ))}
    </div>
  );
}
