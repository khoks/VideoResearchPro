import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import { Button, Textarea } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { NOTE_BODY_MAX_CHARS } from '../../services/notesApi';

interface Props {
  initialBody?: string;
  /** Shown above the textarea; e.g. "Add a note" or "Edit note". */
  heading?: string;
  placeholder?: string;
  saving?: boolean;
  error?: string | null;
  onSave: (bodyMd: string) => void;
  onCancel: () => void;
  autoFocus?: boolean;
}

/**
 * A plain textarea with a Markdown preview — the M5 plan's deliberate choice
 * over a rich-text editor (63–106 kB for formatting the user can type).
 * Ctrl/Cmd+Enter saves, Escape cancels.
 */
export function NoteEditor({
  initialBody = '',
  heading,
  placeholder = 'Write in Markdown. What do you think, and why?',
  saving = false,
  error,
  onSave,
  onCancel,
  autoFocus = true,
}: Props) {
  const c = useColors();
  const [body, setBody] = useState(initialBody);
  const [mode, setMode] = useState<'write' | 'preview'>('write');
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (autoFocus && mode === 'write') ref.current?.focus();
  }, [autoFocus, mode]);

  const trimmed = body.trim();
  const canSave = trimmed.length > 0 && body.length <= NOTE_BODY_MAX_CHARS && !saving;

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      if (canSave) onSave(body);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onCancel();
    }
  };

  const tabStyle = (active: boolean): React.CSSProperties => ({
    background: 'transparent',
    border: 'none',
    padding: `${space['1']} 0`,
    fontFamily: fonts.ui,
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    color: active ? c.accent : c.textMuted,
    borderBottom: `2px solid ${active ? c.accent : 'transparent'}`,
    cursor: 'pointer',
  });

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: space['2'],
        padding: space['3'],
        background: c.surface,
        border: `1px solid ${c.borderStrong}`,
        borderRadius: radius.md,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: space['4'] }}>
        {heading && (
          <span
            style={{
              fontFamily: fonts.display,
              fontSize: fontSize.sm,
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
            }}
          >
            {heading}
          </span>
        )}
        <div style={{ display: 'flex', gap: space['3'], marginLeft: 'auto' }}>
          <button type="button" style={tabStyle(mode === 'write')} onClick={() => setMode('write')}>
            Write
          </button>
          <button
            type="button"
            style={tabStyle(mode === 'preview')}
            onClick={() => setMode('preview')}
            disabled={!trimmed}
          >
            Preview
          </button>
        </div>
      </div>

      {mode === 'write' ? (
        <Textarea
          ref={ref}
          rows={4}
          value={body}
          placeholder={placeholder}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={saving}
          maxLength={NOTE_BODY_MAX_CHARS}
          aria-label={heading ?? 'Note'}
          style={{ fontFamily: fonts.body, fontSize: fontSize.base, lineHeight: lineHeight.normal }}
        />
      ) : (
        <div
          className="reading"
          style={{
            minHeight: 96,
            padding: `${space['2']} ${space['3']}`,
            border: `1px dashed ${c.border}`,
            borderRadius: radius.md,
            color: c.textPrimary,
            fontFamily: fonts.body,
            fontSize: fontSize.base,
            lineHeight: lineHeight.normal,
          }}
        >
          <ReactMarkdown>{body}</ReactMarkdown>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
        <Button size="sm" onClick={() => onSave(body)} disabled={!canSave} loading={saving}>
          Save note
        </Button>
        <Button size="sm" variant="tertiary" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <span
          style={{
            marginLeft: 'auto',
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            color: error ? c.error : c.textMuted,
          }}
          role={error ? 'alert' : undefined}
        >
          {error ?? 'Ctrl+Enter to save · Markdown'}
        </span>
      </div>
    </div>
  );
}
