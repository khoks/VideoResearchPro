import { useState, type KeyboardEvent, type MouseEvent } from 'react';
import axios from 'axios';
import { useCreateNote, useDeleteNote, useNotesForTarget, useUpdateNote } from '../../hooks/useNotes';
import type { NoteTargetType } from '../../services/notesApi';
import { Button } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';
import { NoteCard } from './NoteCard';
import { NoteEditor } from './NoteEditor';
import { inlineErrorMessage } from '../../utils/apiError';

interface Props {
  targetType: NoteTargetType;
  /** The id to WRITE with. Documents accept either `document_id` or the legacy `video_id`. */
  targetId: string;
  /** Every id the caller has for the target, so the list matches notes stored
   * under the canonical id. Defaults to `[targetId]`. */
  matchIds?: Array<string | null | undefined>;
  /**
   * `inline`: a one-line "Notes (n) · Add a note" control inside a row or
   * card, expanding to the list. `section`: always-open list with a heading,
   * for a page-level card.
   */
  variant?: 'inline' | 'section';
  title?: string;
  description?: string;
}

/**
 * What a note's editor says for a failed save, and the only place it is said:
 * both hooks set `meta`, so the global toast stands aside (T-3.4.1.24). The
 * server's words, else a sentence for the status, and nothing for a 401, which
 * the session-expiry path owns.
 */
function errorMessage(err: unknown): string | null {
  const status = axios.isAxiosError(err) ? err.response?.status : undefined;
  if (status === 404) return inlineErrorMessage(err, 'That target is no longer visible to you.');
  if (status === 422) return inlineErrorMessage(err, 'The note could not be saved as written.');
  return inlineErrorMessage(err, 'Could not save the note. Try again.');
}

/**
 * The inline note control and list (T-8.5.1.3). One instance per target;
 * the data comes from a per-type query shared by every instance on the page.
 *
 * Clicks and key presses stop at this panel: it is mounted inside cards that
 * open on click or Enter (the channel row), and typing a note must not open
 * the channel.
 */
export function NotesPanel({
  targetType,
  targetId,
  matchIds,
  variant = 'inline',
  title = 'Your notes',
  description,
}: Props) {
  const c = useColors();
  const ids = matchIds ?? [targetId];
  const { data: notes = [], isLoading } = useNotesForTarget(targetType, ids);
  const createNote = useCreateNote();
  const updateNote = useUpdateNote();
  const deleteNote = useDeleteNote();

  const [open, setOpen] = useState(variant === 'section');
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const count = notes.length;
  const expanded = variant === 'section' || open || adding;
  // While a note is being saved, nothing here may close its editor: the editor
  // is where a failed save is said, and the only place. So adding, editing
  // another note and folding the list wait for the answer (T-3.4.1.24,
  // D-159 point 2).
  const saving = createNote.isPending || updateNote.isPending;

  const stop = (e: MouseEvent | KeyboardEvent) => e.stopPropagation();

  // A new editor starts clean: an earlier failure belongs to the editor it
  // was said in.
  const startAdding = () => {
    setEditingId(null);
    updateNote.reset();
    createNote.reset();
    setAdding(true);
  };
  const startEditing = (id: string) => {
    setAdding(false);
    createNote.reset();
    updateNote.reset();
    setEditingId(id);
  };

  const handleCreate = (body: string) => {
    createNote.mutate(
      { target_type: targetType, target_id: targetId, body_md: body },
      {
        onSuccess: () => {
          setAdding(false);
          setOpen(true);
        },
      },
    );
  };

  const handleUpdate = (id: string, body: string) => {
    updateNote.mutate(
      { id, payload: { body_md: body } },
      { onSuccess: () => setEditingId(null) },
    );
  };

  const labelStyle: React.CSSProperties = {
    fontFamily: fonts.ui,
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    color: c.textSecondary,
  };

  const list = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
      {notes.map((n) =>
        editingId === n.id ? (
          <NoteEditor
            key={n.id}
            heading="Edit note"
            initialBody={n.body_md}
            saving={updateNote.isPending}
            error={updateNote.isError ? errorMessage(updateNote.error) : null}
            onSave={(body) => handleUpdate(n.id, body)}
            onCancel={() => {
              setEditingId(null);
              updateNote.reset();
            }}
          />
        ) : (
          <NoteCard
            key={n.id}
            note={n}
            onEdit={() => startEditing(n.id)}
            editHeld={saving}
            onDelete={() => deleteNote.mutate(n.id)}
            deleting={deleteNote.isPending && deleteNote.variables === n.id}
          />
        ),
      )}
      {adding && (
        <NoteEditor
          heading="Add a note"
          saving={createNote.isPending}
          error={createNote.isError ? errorMessage(createNote.error) : null}
          onSave={handleCreate}
          onCancel={() => {
            setAdding(false);
            createNote.reset();
          }}
        />
      )}
      {variant === 'section' && count === 0 && !adding && !isLoading && (
        <p
          style={{
            margin: 0,
            fontFamily: fonts.body,
            fontSize: fontSize.sm,
            color: c.textMuted,
            lineHeight: lineHeight.normal,
          }}
        >
          Nothing written here yet. A note is your own voice in the library: what you make of this,
          and why.
        </p>
      )}
    </div>
  );

  if (variant === 'section') {
    return (
      <section aria-label={title} onClick={stop} onKeyDown={stop}>
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: space['3'],
            marginBottom: space['3'],
            flexWrap: 'wrap',
          }}
        >
          <h2
            style={{
              margin: 0,
              fontFamily: fonts.display,
              fontSize: fontSize.lg,
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
            }}
          >
            {title}
            {count > 0 ? ` (${count})` : ''}
          </h2>
          {!adding && (
            <Button
              size="sm"
              variant="secondary"
              onClick={startAdding}
              disabled={saving}
              style={{ marginLeft: 'auto' }}
            >
              Add a note
            </Button>
          )}
        </div>
        {description && (
          <p
            style={{
              margin: `0 0 ${space['3']}`,
              fontFamily: fonts.body,
              fontSize: fontSize.sm,
              color: c.textSecondary,
              lineHeight: lineHeight.normal,
            }}
          >
            {description}
          </p>
        )}
        {list}
      </section>
    );
  }

  return (
    <div
      onClick={stop}
      onKeyDown={stop}
      style={{ display: 'flex', flexDirection: 'column', gap: space['2'], marginTop: space['1'] }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
        {count > 0 && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            disabled={saving}
            aria-expanded={expanded}
            style={{
              ...labelStyle,
              background: 'transparent',
              border: 'none',
              padding: 0,
              cursor: saving ? 'default' : 'pointer',
              color: c.accent,
            }}
          >
            {expanded ? '▾' : '▸'} {count === 1 ? '1 note' : `${count} notes`}
          </button>
        )}
        {!adding && (
          <button
            type="button"
            onClick={startAdding}
            disabled={saving}
            style={{
              ...labelStyle,
              background: 'transparent',
              border: 'none',
              padding: 0,
              cursor: saving ? 'default' : 'pointer',
              color: count > 0 ? c.textMuted : c.accent,
            }}
          >
            + Add a note
          </button>
        )}
      </div>
      {expanded && (count > 0 || adding) && list}
    </div>
  );
}
