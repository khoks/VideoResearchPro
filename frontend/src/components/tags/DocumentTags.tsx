import { useMemo } from 'react';
import type { TagSummary } from '../../services/tagsApi';
import { useApplyTag, useCreateTag, useTags, useUnapplyTag } from '../../hooks/useTags';
import { LabelPicker } from '../labels/LabelPicker';
import { LabelPill } from '../primitives';
import { space } from '../../theme';

/** Where a tag chip leads: the library filtered to that tag. */
export function tagHref(tagId: string): string {
  return `/library?tag=${encodeURIComponent(tagId)}`;
}

/**
 * The reader's tags on one document (S-8.1.3): a chip per tag, linking to
 * the library filtered by it, and a "+ Tag" control (checkbox per tag, saved
 * on toggle; inline create applies the new tag at once). Tags are private to
 * the reader and not tier-gated.
 */
export function DocumentTags({ documentId, tags }: { documentId: string; tags: TagSummary[] }) {
  const tagsQuery = useTags();
  const apply = useApplyTag();
  const unapply = useUnapplyTag();
  const create = useCreateTag();
  const selectedIds = useMemo(() => new Set(tags.map((t) => t.id)), [tags]);

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: space['1'] }}>
      {tags.map((tag) => (
        <LabelPill key={tag.id} color={tag.color} to={tagHref(tag.id)} title={`Sources tagged ${tag.name}`}>
          {tag.name}
        </LabelPill>
      ))}
      <LabelPicker
        labels={tagsQuery.data ?? []}
        selectedIds={selectedIds}
        buttonLabel={tags.length === 0 ? '+ Tag' : 'Tags'}
        buttonVariant="tertiary"
        dialogLabel="Tags for this source"
        emptyText="No tags yet. Name one below."
        createPlaceholder="New tag…"
        createAriaLabel="New tag name"
        canWrite
        isLoading={tagsQuery.isLoading}
        busy={apply.isPending || unapply.isPending || create.isPending}
        align="left"
        onToggle={(tag, selected) =>
          (selected ? apply : unapply).mutateAsync({ documentId, tagId: tag.id })
        }
        onCreate={async (name) => {
          const tag = await create.mutateAsync({ name });
          await apply.mutateAsync({ documentId, tagId: tag.id });
        }}
      />
    </div>
  );
}
