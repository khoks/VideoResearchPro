import { useState } from 'react';
import type { Shelf } from '../../services/shelvesApi';
import { useDeleteShelf } from '../../hooks/useShelves';
import { Button, Modal } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize } from '../../theme';
import { inlineErrorMessage } from '../../utils/apiError';

interface Props {
  shelf: Pick<Shelf, 'id' | 'name' | 'job_count'> | null;
  onClose: () => void;
  onDeleted?: () => void;
}

/** Confirms a shelf delete and says plainly that its runs are kept. */
export function DeleteShelfModal({ shelf, onClose, onDeleted }: Props) {
  const c = useColors();
  const del = useDeleteShelf();
  const [error, setError] = useState<string | null>(null);

  // A line from one opening never shows on the next, for this shelf or another:
  // both pages keep the modal mounted and only change `shelf`.
  const [shownFor, setShownFor] = useState(shelf?.id);
  if (shelf?.id !== shownFor) {
    setShownFor(shelf?.id);
    setError(null);
  }

  // The modal is where a failure is said, and the only place (T-3.4.1.18), so it
  // stays open until the answer comes: Escape and the backdrop wait, as
  // "Keep it" does. Closed early, a failure would be said nowhere.
  const dismiss = () => {
    if (!del.isPending) onClose();
  };

  const confirm = () => {
    if (!shelf) return;
    setError(null);
    del.mutate(shelf.id, {
      onSuccess: () => {
        onClose();
        onDeleted?.();
      },
      // Said here alone: the hook sets `meta`, and a 401 says nothing (T-3.4.1.18).
      onError: (err) => setError(inlineErrorMessage(err, 'Could not delete the shelf.')),
    });
  };

  const runs = shelf?.job_count ?? 0;
  return (
    <Modal
      open={!!shelf}
      onClose={dismiss}
      title="Delete this shelf?"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={del.isPending}>
            Keep it
          </Button>
          <Button variant="danger" onClick={confirm} loading={del.isPending}>
            Delete shelf
          </Button>
        </>
      }
    >
      <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.base }}>
        <strong>{shelf?.name}</strong> goes away.{' '}
        {runs > 0
          ? `Its ${runs} ${runs === 1 ? 'run stays' : 'runs stay'} in Active runs, with their reports, answers and sources.`
          : 'It holds no runs.'}
      </p>
      {error && (
        <p role="alert" style={{ margin: '0.75rem 0 0', fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error }}>
          {error}
        </p>
      )}
    </Modal>
  );
}
