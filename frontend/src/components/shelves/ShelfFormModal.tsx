import { useEffect, useState } from 'react';
import type { ShelfColor } from '../../services/shelvesApi';
import { PaletteField } from '../labels/PaletteField';
import { Button, FormField, Input, Modal, Textarea } from '../primitives';
import { space } from '../../theme';
import { inlineErrorMessage } from '../../utils/apiError';

export interface ShelfFormValues {
  name: string;
  description: string | null;
  color: ShelfColor;
}

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  submitLabel: string;
  /** Pre-fill for rename / recolour; omit for a new shelf. */
  initial?: ShelfFormValues | null;
  /** Rejections surface inline (a 409 "You already have a shelf named …" reads
   * verbatim), and only there: the mutation behind it sets `meta`, so the global
   * toast stands aside (T-3.4.1.22). */
  onSubmit: (values: ShelfFormValues) => Promise<unknown>;
}

/** Create or edit a shelf: name, optional description, one of ten palette colours. */
export function ShelfFormModal({ open, onClose, title, submitLabel, initial, onSubmit }: Props) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState<ShelfColor>('default');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Filled afresh on each opening. Keyed on the values, not the object: a page
  // that builds `initial` on every render (the shelves page) would otherwise
  // reset the form, and wipe its failure line, each time a request's state
  // changed, and with the global toast standing aside that failure would be
  // said nowhere (T-3.4.1.22).
  const initialName = initial?.name ?? '';
  const initialDescription = initial?.description ?? '';
  const initialColor = initial?.color ?? 'default';
  useEffect(() => {
    if (!open) return;
    setName(initialName);
    setDescription(initialDescription);
    setColor(initialColor);
    setError(null);
    setBusy(false);
  }, [open, initialName, initialDescription, initialColor]);

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError('Give the shelf a name.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit({
        name: trimmed,
        description: description.trim() ? description.trim() : null,
        color,
      });
      onClose();
    } catch (err) {
      // A 401 says nothing: the session-expiry path owns it.
      setError(inlineErrorMessage(err, 'Could not save the shelf.'));
    } finally {
      setBusy(false);
    }
  };

  // The form is where a failure is said, and the only place, so it stays open
  // until the answer comes: Escape and the backdrop wait, as Cancel does.
  // Closed early, a failure would be said nowhere (D-156 point 2).
  const dismiss = () => {
    if (!busy) onClose();
  };

  return (
    <Modal
      open={open}
      onClose={dismiss}
      title={title}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy}>
            {submitLabel}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}
      >
        <FormField label="Name" required errorText={error ?? undefined}>
          {(id) => (
            <Input
              id={id}
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
              placeholder="e.g. Macroeconomics"
              autoFocus
            />
          )}
        </FormField>
        <FormField label="Description" optional>
          {(id) => (
            <Textarea
              id={id}
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
              placeholder="What belongs here"
            />
          )}
        </FormField>
        <PaletteField value={color} onChange={setColor} />
        {/* Lets Enter in the name field submit without a visible second button. */}
        <button type="submit" hidden aria-hidden tabIndex={-1} />
      </form>
    </Modal>
  );
}
