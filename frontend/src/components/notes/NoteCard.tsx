import { useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Note } from '../../services/notesApi';
import { formatDate } from '../../utils/formatters';
import { Button } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';

interface Props {
  note: Note;
  onEdit?: () => void;
  onDelete?: () => void;
  deleting?: boolean;
  /** Optional line under the date, e.g. the target on the notes page. */
  meta?: ReactNode;
}

function selectorAnchor(note: Note): string | null {
  const s = note.selector;
  if (!s) return null;
  const parts: string[] = [];
  if (typeof s.start_seconds === 'number') {
    const m = Math.floor(s.start_seconds / 60);
    const sec = Math.floor(s.start_seconds % 60);
    parts.push(`at ${m}:${String(sec).padStart(2, '0')}`);
  }
  if (s.exact) parts.push(`“${s.exact}”`);
  return parts.length ? parts.join(' · ') : null;
}

/** One note, rendered. The phrasing "You wrote this on …" is the citation
 * form S-8.5.2 will use, so the user meets it here first. */
export function NoteCard({ note, onEdit, onDelete, deleting, meta }: Props) {
  const c = useColors();
  const [confirming, setConfirming] = useState(false);
  const anchor = selectorAnchor(note);
  const edited = note.updated_at !== note.created_at;

  return (
    <article
      aria-label="Your note"
      style={{
        padding: `${space['3']} ${space['4']}`,
        background: c.surface,
        border: `1px solid ${c.border}`,
        borderLeft: `3px solid ${c.gold}`,
        borderRadius: radius.md,
        display: 'flex',
        flexDirection: 'column',
        gap: space['2'],
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: space['3'], flexWrap: 'wrap' }}>
        <span
          style={{
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            fontWeight: fontWeight.medium,
            color: c.textSecondary,
            letterSpacing: '0.02em',
          }}
          title={edited ? `Edited ${formatDate(note.updated_at)}` : undefined}
        >
          You wrote this on {formatDate(note.created_at)}
          {edited ? ' · edited' : ''}
          {note.motivation !== 'commenting' ? ` · ${note.motivation}` : ''}
        </span>
        {(onEdit || onDelete) && (
          <div style={{ marginLeft: 'auto', display: 'flex', gap: space['1'], alignItems: 'center' }}>
            {confirming ? (
              <>
                <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary }}>
                  Delete this note?
                </span>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => {
                    onDelete?.();
                    setConfirming(false);
                  }}
                  loading={deleting}
                >
                  Delete
                </Button>
                <Button size="sm" variant="tertiary" onClick={() => setConfirming(false)}>
                  Keep
                </Button>
              </>
            ) : (
              <>
                {onEdit && (
                  <Button size="sm" variant="tertiary" onClick={onEdit}>
                    Edit
                  </Button>
                )}
                {onDelete && (
                  <Button size="sm" variant="tertiary" onClick={() => setConfirming(true)}>
                    Delete
                  </Button>
                )}
              </>
            )}
          </div>
        )}
      </div>
      {meta && (
        <div style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>{meta}</div>
      )}
      {anchor && (
        <div
          style={{
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            color: c.textMuted,
            fontStyle: 'italic',
          }}
        >
          {anchor}
        </div>
      )}
      <div
        className="reading"
        style={{
          color: c.textPrimary,
          fontFamily: fonts.body,
          fontSize: fontSize.base,
          lineHeight: lineHeight.normal,
          maxWidth: 'none',
          overflowWrap: 'anywhere',
        }}
      >
        <ReactMarkdown>{note.body_md}</ReactMarkdown>
      </div>
    </article>
  );
}
