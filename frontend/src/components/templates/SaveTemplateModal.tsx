import { useEffect, useState } from 'react';
import { Button, FormField, Input, Modal, Textarea } from '../primitives';
import { space } from '../../theme';
import { inlineErrorMessage } from '../../utils/apiError';

interface Props {
  open: boolean;
  onClose: () => void;
  title?: string;
  submitLabel?: string;
  initialName?: string;
  initialDescription?: string | null;
  /** Rejections read inline in the server's words (a 409 name collision), and
   * only there: the mutation behind it sets `meta`, so the global toast stands
   * aside (T-3.4.1.22). */
  onSubmit: (values: { name: string; description: string | null }) => Promise<unknown>;
}

/** Name (and optionally describe) a template. Used by "Save as template"
 * on a run, by the submit form, and for renames on /templates. */
export function SaveTemplateModal({
  open,
  onClose,
  title = 'Save as template',
  submitLabel = 'Save template',
  initialName = '',
  initialDescription = null,
  onSubmit,
}: Props) {
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription ?? '');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(initialName);
    setDescription(initialDescription ?? '');
    setError(null);
    setBusy(false);
  }, [open, initialName, initialDescription]);

  const submit = async () => {
    if (!name.trim()) {
      setError('Give the template a name.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ name: name.trim(), description: description.trim() || null });
      onClose();
    } catch (err) {
      // A 401 says nothing: the session-expiry path owns it.
      setError(inlineErrorMessage(err, 'Could not save the template.'));
    } finally {
      setBusy(false);
    }
  };

  // The dialog is where a failure is said, and the only place, so it stays open
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
        <FormField
          label="Name"
          required
          errorText={error ?? undefined}
          helperText="Everything but the topic is saved; you type a new topic each time."
        >
          {(id) => (
            <Input
              id={id}
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
              placeholder="e.g. Weekly AI policy scan"
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
            />
          )}
        </FormField>
        <button type="submit" hidden aria-hidden tabIndex={-1} />
      </form>
    </Modal>
  );
}
