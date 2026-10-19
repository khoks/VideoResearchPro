import { useState } from 'react';
import type { Tag } from '../../services/tagsApi';
import { useDeleteTag, useTags, useUpdateTag } from '../../hooks/useTags';
import { PaletteField } from '../labels/PaletteField';
import { Button, Input, LabelPill, Modal, Select, Spinner } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, radius, space } from '../../theme';
import type { PaletteColor } from '../../theme';
import { apiErrorMessage } from '../../utils/apiError';

/**
 * Rename, recolour, merge and delete the reader's tags (S-8.1.3). A rename
 * keeps the tag's id, so every source carrying it follows; a merge folds one
 * tag into another and drops duplicates; a delete removes the tag from every
 * source and leaves the sources alone.
 */
export function TagsManagerModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const c = useColors();
  const tagsQuery = useTags();
  const tags = tagsQuery.data ?? [];

  return (
    <Modal open={open} onClose={onClose} title="Your tags" footer={null} maxWidth={640}>
      {tagsQuery.isLoading ? (
        <Spinner size={18} />
      ) : tags.length === 0 ? (
        <p style={{ margin: 0, fontFamily: fonts.body, color: c.textSecondary }}>
          No tags yet. Use “+ Tag” on any source to make one.
        </p>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
          {tags.map((tag) => (
            <TagRow key={tag.id} tag={tag} others={tags.filter((t) => t.id !== tag.id)} />
          ))}
        </ul>
      )}
    </Modal>
  );
}

function TagRow({ tag, others }: { tag: Tag; others: Tag[] }) {
  const c = useColors();
  const update = useUpdateTag();
  const del = useDeleteTag();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(tag.name);
  const [color, setColor] = useState<PaletteColor>(tag.color);
  const [mergeInto, setMergeInto] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startEdit = () => {
    setName(tag.name);
    setColor(tag.color);
    setMergeInto('');
    setConfirmDelete(false);
    setError(null);
    setEditing(true);
  };

  const save = () => {
    setError(null);
    update.mutate(
      { id: tag.id, body: { name: name.trim(), color } },
      {
        onSuccess: () => setEditing(false),
        onError: (err) => setError(apiErrorMessage(err, 'Could not save the tag.')),
      },
    );
  };

  const merge = () => {
    if (!mergeInto) return;
    setError(null);
    del.mutate(
      { id: tag.id, into: mergeInto },
      { onError: (err) => setError(apiErrorMessage(err, 'Could not merge the tag.')) },
    );
  };

  const remove = () => {
    setError(null);
    del.mutate({ id: tag.id }, { onError: (err) => setError(apiErrorMessage(err, 'Could not delete the tag.')) });
  };

  return (
    <li
      style={{
        border: `1px solid ${c.border}`,
        borderRadius: radius.md,
        padding: `${space['2']} ${space['3']}`,
        display: 'flex',
        flexDirection: 'column',
        gap: space['2'],
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
        <LabelPill color={tag.color}>{tag.name}</LabelPill>
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, flex: 1 }}>
          {tag.document_count} {tag.document_count === 1 ? 'source' : 'sources'}
        </span>
        {!editing && (
          <Button size="sm" variant="tertiary" onClick={startEdit}>
            Edit
          </Button>
        )}
      </div>

      {editing && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          <div style={{ display: 'flex', gap: space['2'], alignItems: 'center' }}>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={60}
              aria-label={`New name for ${tag.name}`}
              style={{ padding: `${space['1']} ${space['2']}`, fontSize: fontSize.sm }}
            />
            <Button size="sm" onClick={save} loading={update.isPending} disabled={!name.trim()}>
              Save
            </Button>
            <Button size="sm" variant="tertiary" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
          <PaletteField value={color} onChange={setColor} />
          {others.length > 0 && (
            <div style={{ display: 'flex', gap: space['2'], alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
                Merge into
              </span>
              <div style={{ flex: '1 1 160px' }}>
                <Select
                  value={mergeInto}
                  onChange={(e) => setMergeInto(e.target.value)}
                  aria-label={`Merge ${tag.name} into`}
                >
                  <option value="">Choose a tag…</option>
                  {others.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </Select>
              </div>
              <Button size="sm" variant="secondary" onClick={merge} disabled={!mergeInto || del.isPending}>
                Merge
              </Button>
            </div>
          )}
          <div>
            {confirmDelete ? (
              <span style={{ display: 'inline-flex', gap: space['2'], alignItems: 'center' }}>
                <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
                  Remove “{tag.name}” from {tag.document_count} {tag.document_count === 1 ? 'source' : 'sources'}?
                </span>
                <Button size="sm" variant="danger" onClick={remove} loading={del.isPending}>
                  Delete tag
                </Button>
                <Button size="sm" variant="tertiary" onClick={() => setConfirmDelete(false)}>
                  Keep it
                </Button>
              </span>
            ) : (
              <Button size="sm" variant="tertiary" onClick={() => setConfirmDelete(true)}>
                Delete…
              </Button>
            )}
          </div>
        </div>
      )}

      {error && (
        <p role="alert" style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.error }}>
          {error}
        </p>
      )}
    </li>
  );
}
