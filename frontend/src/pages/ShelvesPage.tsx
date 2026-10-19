import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useCreateShelf, useShelves, useUpdateShelf } from '../hooks/useShelves';
import { useTierCapabilities } from '../hooks/useTierCapabilities';
import {
  DeleteShelfModal,
  ShelfDot,
  ShelfFormModal,
  type ShelfFormValues,
} from '../components/shelves';
import { Button, Card, EmptyState, Skeleton } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../theme';
import { formatDate } from '../utils/formatters';
import type { Shelf } from '../services/shelvesApi';

/**
 * `/shelves` — every shelf this reader owns, with create / rename /
 * recolour / delete (S-8.1.2). Shelves are a Pro feature; a reader whose
 * plan no longer includes them keeps the list read-only (S-8.1.1 decision).
 */
export function ShelvesPage() {
  const c = useColors();
  const navigate = useNavigate();
  const { has } = useTierCapabilities();
  const canWrite = has('shelves');
  const shelvesQuery = useShelves();
  const create = useCreateShelf();
  const update = useUpdateShelf();

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Shelf | null>(null);
  const [deleting, setDeleting] = useState<Shelf | null>(null);

  const shelves = shelvesQuery.data ?? [];

  const createShelf = async (v: ShelfFormValues) => {
    const shelf = await create.mutateAsync(v);
    navigate(`/shelves/${shelf.id}`);
  };
  const saveShelf = (v: ShelfFormValues) =>
    update.mutateAsync({ id: editing!.id, body: v });

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
      <header
        style={{
          marginBottom: space['5'],
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: space['4'],
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h1
            style={{
              fontFamily: fonts.display,
              fontSize: fontSize['2xl'],
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
              margin: 0,
              lineHeight: lineHeight.tight,
            }}
          >
            Shelves
          </h1>
          <p
            style={{
              fontFamily: fonts.body,
              fontStyle: 'italic',
              fontSize: fontSize.sm,
              color: c.textMuted,
              margin: `${space['2']} 0 0`,
            }}
          >
            Group your runs into the projects they belong to.
          </p>
        </div>
        {canWrite && shelves.length > 0 && (
          <Button onClick={() => setCreating(true)}>New shelf</Button>
        )}
      </header>

      {!canWrite && shelves.length > 0 && (
        <p
          style={{
            margin: `0 0 ${space['4']}`,
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            color: c.textSecondary,
          }}
        >
          Your plan keeps these shelves read-only.{' '}
          <Link to="/account/subscription" style={{ color: c.accent }}>
            Upgrade
          </Link>{' '}
          to create or change them.
        </p>
      )}

      {shelvesQuery.isLoading ? (
        <div aria-busy style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          <Skeleton variant="row" height={72} />
          <Skeleton variant="row" height={72} />
        </div>
      ) : shelvesQuery.isError ? (
        <EmptyState
          title="Couldn't load your shelves."
          description="Something blocked the fetch."
          action={
            <Button variant="secondary" onClick={() => void shelvesQuery.refetch()}>
              Retry
            </Button>
          }
        />
      ) : shelves.length === 0 ? (
        canWrite ? (
          <EmptyState
            title="No shelves yet."
            description="A shelf gathers the runs of one project, so you can open them together and, soon, ask across just them."
            action={<Button onClick={() => setCreating(true)}>New shelf</Button>}
          />
        ) : (
          <EmptyState
            title="Shelves come with Pro."
            description="Group runs into projects and open each project's sources together."
            action={
              <Button variant="secondary" onClick={() => navigate('/account/subscription')}>
                See plans
              </Button>
            }
          />
        )
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          {shelves.map((shelf) => (
            <Card key={shelf.id}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: space['4'],
                  flexWrap: 'wrap',
                }}
              >
                <div style={{ flex: '1 1 280px', minWidth: 0 }}>
                  <Link
                    to={`/shelves/${shelf.id}`}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: space['2'],
                      fontFamily: fonts.display,
                      fontSize: fontSize.md,
                      fontWeight: fontWeight.semibold,
                      color: c.textPrimary,
                      textDecoration: 'none',
                      maxWidth: '100%',
                    }}
                  >
                    <ShelfDot color={shelf.color} size={12} />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {shelf.name}
                    </span>
                  </Link>
                  {shelf.description && (
                    <p
                      style={{
                        margin: `${space['1']} 0 0`,
                        fontFamily: fonts.body,
                        fontSize: fontSize.sm,
                        color: c.textSecondary,
                      }}
                    >
                      {shelf.description}
                    </p>
                  )}
                  <p
                    style={{
                      margin: `${space['1']} 0 0`,
                      fontFamily: fonts.ui,
                      fontSize: fontSize.xs,
                      color: c.textMuted,
                    }}
                  >
                    {shelf.job_count} {shelf.job_count === 1 ? 'run' : 'runs'} · updated{' '}
                    {formatDate(shelf.updated_at)}
                  </p>
                </div>
                {canWrite && (
                  <div style={{ display: 'flex', gap: space['2'], flexShrink: 0 }}>
                    <Button size="sm" variant="tertiary" onClick={() => setEditing(shelf)}>
                      Edit
                    </Button>
                    <Button size="sm" variant="tertiary" onClick={() => setDeleting(shelf)}>
                      Delete
                    </Button>
                  </div>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <ShelfFormModal
        open={creating}
        onClose={() => setCreating(false)}
        title="New shelf"
        submitLabel="Create shelf"
        onSubmit={createShelf}
      />
      <ShelfFormModal
        open={!!editing}
        onClose={() => setEditing(null)}
        title="Edit shelf"
        submitLabel="Save"
        initial={
          editing
            ? { name: editing.name, description: editing.description, color: editing.color }
            : null
        }
        onSubmit={saveShelf}
      />
      <DeleteShelfModal shelf={deleting} onClose={() => setDeleting(null)} />
    </div>
  );
}
