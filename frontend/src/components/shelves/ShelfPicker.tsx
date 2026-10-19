import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  useAddJobToShelf,
  useCreateShelf,
  useJobShelves,
  useRemoveJobFromShelf,
  useShelves,
} from '../../hooks/useShelves';
import { useTierCapabilities } from '../../hooks/useTierCapabilities';
import { useColors, useShadows } from '../../hooks/useTheme';
import { Button, Input, Spinner } from '../primitives';
import { ShelfDot } from './ShelfDot';
import { fonts, fontSize, radius, space, z } from '../../theme';
import { apiErrorMessage } from '../../utils/apiError';

interface Props {
  jobId: string;
  size?: 'sm' | 'md';
}

/**
 * "Add to shelf": a button that reads "On N shelves" once the run is shelved,
 * opening a popover with one checkbox per shelf (multi-select, each toggle
 * saved at once) and an inline "New shelf…" field that creates and adds in
 * one go. Free-tier readers keep read access (links to the shelves the run
 * is on, no checkboxes) and see nothing when it is on none.
 */
export function ShelfPicker({ jobId, size = 'sm' }: Props) {
  const c = useColors();
  const s = useShadows();
  const { has } = useTierCapabilities();
  const canWrite = has('shelves');

  const shelvesQuery = useShelves();
  const onShelvesQuery = useJobShelves(jobId);
  const add = useAddJobToShelf();
  const remove = useRemoveJobFromShelf();
  const create = useCreateShelf();

  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const shelves = shelvesQuery.data ?? [];
  const onIds = new Set((onShelvesQuery.data ?? []).map((sh) => sh.id));
  const count = onIds.size;

  if (!canWrite && count === 0) return null;

  const busy = add.isPending || remove.isPending || create.isPending;
  const label = count === 0 ? 'Add to shelf' : `On ${count} ${count === 1 ? 'shelf' : 'shelves'}`;

  const toggle = (shelfId: string) => {
    setError(null);
    const mutation = onIds.has(shelfId) ? remove : add;
    mutation.mutate(
      { shelfId, jobId },
      { onError: (err) => setError(apiErrorMessage(err, 'Could not update the shelf.')) },
    );
  };

  const createAndAdd = async () => {
    const name = newName.trim();
    if (!name) return;
    setError(null);
    try {
      const shelf = await create.mutateAsync({ name });
      await add.mutateAsync({ shelfId: shelf.id, jobId });
      setNewName('');
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not create the shelf.'));
    }
  };

  const rowStyle = {
    display: 'flex',
    alignItems: 'center',
    gap: space['2'],
    padding: `${space['1']} ${space['2']}`,
    borderRadius: radius.sm,
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    color: c.textPrimary,
    minWidth: 0,
  } as const;
  const nameStyle = { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } as const;

  return (
    <div
      ref={rootRef}
      style={{ position: 'relative', display: 'inline-block' }}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <Button
        size={size}
        variant={count > 0 ? 'secondary' : 'tertiary'}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        {label}
      </Button>

      {open && (
        <div
          role="dialog"
          aria-label="Shelves for this run"
          style={{
            position: 'absolute',
            top: 'calc(100% + 4px)',
            right: 0,
            zIndex: z.drawer,
            minWidth: 260,
            maxWidth: 320,
            background: c.surface,
            border: `1px solid ${c.border}`,
            borderRadius: radius.md,
            boxShadow: s.floating,
            padding: space['3'],
            display: 'flex',
            flexDirection: 'column',
            gap: space['2'],
            textAlign: 'left',
          }}
        >
          {shelvesQuery.isLoading ? (
            <Spinner size={14} />
          ) : shelves.length === 0 ? (
            <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>
              No shelves yet. Name one below.
            </p>
          ) : (
            <ul
              style={{
                listStyle: 'none',
                margin: 0,
                padding: 0,
                maxHeight: 240,
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
              }}
            >
              {shelves.map((shelf) => {
                const on = onIds.has(shelf.id);
                if (!canWrite && !on) return null;
                return (
                  <li key={shelf.id}>
                    {canWrite ? (
                      <label style={{ ...rowStyle, cursor: busy ? 'wait' : 'pointer' }}>
                        <input
                          type="checkbox"
                          checked={on}
                          disabled={busy}
                          onChange={() => toggle(shelf.id)}
                          style={{ accentColor: c.accent, margin: 0 }}
                        />
                        <ShelfDot color={shelf.color} />
                        <span style={nameStyle}>{shelf.name}</span>
                      </label>
                    ) : (
                      <Link to={`/shelves/${shelf.id}`} style={{ ...rowStyle, textDecoration: 'none' }}>
                        <ShelfDot color={shelf.color} />
                        <span style={nameStyle}>{shelf.name}</span>
                      </Link>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {canWrite && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void createAndAdd();
              }}
              style={{
                display: 'flex',
                gap: space['2'],
                alignItems: 'center',
                borderTop: `1px solid ${c.border}`,
                paddingTop: space['2'],
              }}
            >
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="New shelf…"
                aria-label="New shelf name"
                maxLength={120}
                style={{ padding: `${space['1']} ${space['2']}`, fontSize: fontSize.sm }}
              />
              <Button size="sm" type="submit" disabled={!newName.trim() || busy}>
                Create
              </Button>
            </form>
          )}

          {error && (
            <p role="alert" style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.error }}>
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
