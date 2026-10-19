import { useState } from 'react';
import { useTags } from '../../hooks/useTags';
import { Button, LabelPill, Select } from '../primitives';
import { TagsManagerModal } from './TagsManagerModal';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, space } from '../../theme';

/**
 * The Library's tag filter (S-8.1.3): a tag select, the active tag as a pill
 * with Clear, and "Manage tags". The value lives in the URL (`?tag=`) so a
 * tag chip anywhere in the app is just a link.
 */
export function TagFilterBar({ value, onChange }: { value: string; onChange: (tagId: string) => void }) {
  const c = useColors();
  const tagsQuery = useTags();
  const [managing, setManaging] = useState(false);
  const tags = tagsQuery.data ?? [];
  const active = tags.find((t) => t.id === value);

  if (tags.length === 0 && !value) return null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: space['3'],
        flexWrap: 'wrap',
        marginBottom: space['3'],
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        color: c.textSecondary,
      }}
    >
      <span>Tag</span>
      <div style={{ flex: '0 0 200px' }}>
        <Select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Filter by tag">
          <option value="">All tags</option>
          {tags.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.document_count})
            </option>
          ))}
        </Select>
      </div>
      {value && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: space['2'] }}>
          Filtering by{' '}
          {active ? <LabelPill color={active.color}>{active.name}</LabelPill> : <em>a tag you no longer have</em>}
          <Button size="sm" variant="tertiary" onClick={() => onChange('')}>
            Clear
          </Button>
        </span>
      )}
      <Button size="sm" variant="tertiary" onClick={() => setManaging(true)} style={{ marginLeft: 'auto' }}>
        Manage tags
      </Button>
      <TagsManagerModal open={managing} onClose={() => setManaging(false)} />
    </div>
  );
}
