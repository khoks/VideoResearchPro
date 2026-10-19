import { useMemo } from 'react';
import {
  useAddJobToShelf,
  useCreateShelf,
  useJobShelves,
  useRemoveJobFromShelf,
  useShelves,
} from '../../hooks/useShelves';
import { useTierCapabilities } from '../../hooks/useTierCapabilities';
import { LabelPicker } from '../labels/LabelPicker';

interface Props {
  jobId: string;
  size?: 'sm' | 'md';
}

/**
 * "Add to shelf": reads "On N shelves" once the run is shelved; opens a
 * checkbox per shelf (saved on toggle) and an inline "New shelf…" that
 * creates and adds in one go. Readers without the `shelves` capability keep
 * read access (links to the shelves the run is on) and see nothing when it
 * is on none.
 */
export function ShelfPicker({ jobId, size = 'sm' }: Props) {
  const { has } = useTierCapabilities();
  const canWrite = has('shelves');
  const shelvesQuery = useShelves();
  const { shelves: onShelves } = useJobShelves(jobId);
  const add = useAddJobToShelf();
  const remove = useRemoveJobFromShelf();
  const create = useCreateShelf();

  const selectedIds = useMemo(() => new Set(onShelves.map((s) => s.id)), [onShelves]);
  const count = selectedIds.size;
  if (!canWrite && count === 0) return null;

  return (
    <LabelPicker
      labels={shelvesQuery.data ?? []}
      selectedIds={selectedIds}
      buttonLabel={count === 0 ? 'Add to shelf' : `On ${count} ${count === 1 ? 'shelf' : 'shelves'}`}
      size={size}
      dialogLabel="Shelves for this run"
      emptyText="No shelves yet. Name one below."
      createPlaceholder="New shelf…"
      createAriaLabel="New shelf name"
      canWrite={canWrite}
      hrefFor={(s) => `/shelves/${s.id}`}
      isLoading={shelvesQuery.isLoading}
      busy={add.isPending || remove.isPending || create.isPending}
      onToggle={(shelf, selected) =>
        (selected ? add : remove).mutateAsync({ shelfId: shelf.id, jobId })
      }
      onCreate={async (name) => {
        const shelf = await create.mutateAsync({ name });
        await add.mutateAsync({ shelfId: shelf.id, jobId });
      }}
    />
  );
}
