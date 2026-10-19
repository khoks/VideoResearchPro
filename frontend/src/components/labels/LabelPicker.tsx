import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useColors, usePaletteColor, useShadows } from '../../hooks/useTheme';
import { Button, Input, Spinner } from '../primitives';
import { fonts, fontSize, radius, space, z } from '../../theme';
import { apiErrorMessage } from '../../utils/apiError';

export interface PickerLabel {
  id: string;
  name: string;
  color: string;
}

interface Props {
  /** Every label the reader owns. */
  labels: PickerLabel[];
  /** Ids of the labels on the thing being labelled. */
  selectedIds: ReadonlySet<string>;
  /** Button text, e.g. "Add to shelf" / "On 2 shelves" or "+ Tag". */
  buttonLabel: ReactNode;
  buttonVariant?: 'secondary' | 'tertiary';
  size?: 'sm' | 'md';
  dialogLabel: string;
  emptyText: string;
  createPlaceholder: string;
  createAriaLabel: string;
  /** False: read-only, the popover lists the selected labels as links. */
  canWrite: boolean;
  /** Link for a label in read-only mode. */
  hrefFor?: (label: PickerLabel) => string;
  isLoading?: boolean;
  busy?: boolean;
  onToggle: (label: PickerLabel, selected: boolean) => Promise<unknown>;
  /** Creates a label and applies it. */
  onCreate: (name: string) => Promise<unknown>;
  /** Alignment of the popover under the button. */
  align?: 'left' | 'right';
}

/**
 * A button that opens a small popover: one checkbox per label, saved on
 * toggle, and an inline field that creates a new label and applies it. The
 * shared engine behind "Add to shelf" (S-8.1.2) and the tag control on
 * library rows (S-8.1.3). Errors (a 409 name collision, a 403 tier gate)
 * read inline in the server's own words.
 */
export function LabelPicker({
  labels,
  selectedIds,
  buttonLabel,
  buttonVariant,
  size = 'sm',
  dialogLabel,
  emptyText,
  createPlaceholder,
  createAriaLabel,
  canWrite,
  hrefFor,
  isLoading,
  busy,
  onToggle,
  onCreate,
  align = 'right',
}: Props) {
  const c = useColors();
  const s = useShadows();
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [anchor, setAnchor] = useState<CSSProperties | null>(null);

  // The popover is portalled to <body> with fixed coordinates taken from the
  // button: every Card sets a transform, which makes it its own stacking
  // context, so an in-flow popover is painted under the NEXT card on a list.
  const place = useCallback(() => {
    const rect = rootRef.current?.getBoundingClientRect();
    if (!rect) return;
    setAnchor({
      top: rect.bottom + 4,
      ...(align === 'right'
        ? { right: Math.max(8, window.innerWidth - rect.right) }
        : { left: Math.max(8, rect.left) }),
    });
  }, [align]);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (rootRef.current?.contains(target) || panelRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    // Capture phase: the wrapper stops propagation (so a click never opens
    // the card behind it), which would otherwise hide these from the document.
    document.addEventListener('mousedown', onDown, true);
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('mousedown', onDown, true);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [open]);

  const toggle = async (label: PickerLabel) => {
    setError(null);
    try {
      await onToggle(label, !selectedIds.has(label.id));
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not save that change.'));
    }
  };

  const create = async () => {
    const name = newName.trim();
    if (!name) return;
    setError(null);
    try {
      await onCreate(name);
      setNewName('');
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not create it.'));
    }
  };

  const visible = canWrite ? labels : labels.filter((l) => selectedIds.has(l.id));
  const rowStyle = {
    display: 'flex',
    alignItems: 'center',
    gap: space['2'],
    padding: `${space['1']} ${space['2']}`,
    borderRadius: radius.sm,
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    color: c.textPrimary,
    minWidth: 0,
  } as const;
  const nameStyle = { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } as const;

  return (
    <div
      ref={rootRef}
      style={{ position: 'relative', display: 'inline-block' }}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <Button
        size={size}
        variant={buttonVariant ?? (selectedIds.size > 0 ? 'secondary' : 'tertiary')}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        {buttonLabel}
      </Button>

      {open && anchor && createPortal(
        <div
          ref={panelRef}
          role="dialog"
          aria-label={dialogLabel}
          style={{
            position: 'fixed',
            ...anchor,
            zIndex: z.drawer,
            minWidth: 260,
            maxWidth: 320,
            background: c.surface,
            border: `1px solid ${c.border}`,
            borderRadius: radius.md,
            boxShadow: s.floating,
            padding: space['3'],
            display: 'flex',
            flexDirection: 'column',
            gap: space['2'],
            textAlign: 'left',
          }}
        >
          {isLoading ? (
            <Spinner size={14} />
          ) : visible.length === 0 ? (
            <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>
              {emptyText}
            </p>
          ) : (
            <ul
              style={{
                listStyle: 'none',
                margin: 0,
                padding: 0,
                maxHeight: 240,
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
              }}
            >
              {visible.map((label) => (
                <li key={label.id}>
                  {canWrite ? (
                    <label style={{ ...rowStyle, cursor: busy ? 'wait' : 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(label.id)}
                        disabled={busy}
                        onChange={() => void toggle(label)}
                        style={{ accentColor: c.accent, margin: 0 }}
                      />
                      <Dot color={label.color} />
                      <span style={nameStyle}>{label.name}</span>
                    </label>
                  ) : hrefFor ? (
                    <Link to={hrefFor(label)} style={{ ...rowStyle, textDecoration: 'none' }}>
                      <Dot color={label.color} />
                      <span style={nameStyle}>{label.name}</span>
                    </Link>
                  ) : (
                    <span style={rowStyle}>
                      <Dot color={label.color} />
                      <span style={nameStyle}>{label.name}</span>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}

          {canWrite && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void create();
              }}
              style={{
                display: 'flex',
                gap: space['2'],
                alignItems: 'center',
                borderTop: `1px solid ${c.border}`,
                paddingTop: space['2'],
              }}
            >
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={createPlaceholder}
                aria-label={createAriaLabel}
                maxLength={120}
                style={{ padding: `${space['1']} ${space['2']}`, fontSize: fontSize.sm }}
              />
              <Button size="sm" type="submit" disabled={!newName.trim() || busy}>
                Create
              </Button>
            </form>
          )}

          {error && (
            <p role="alert" style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.error }}>
              {error}
            </p>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}

function Dot({ color }: { color: string }) {
  const p = usePaletteColor(color);
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block',
        width: 10,
        height: 10,
        borderRadius: '50%',
        background: p.bg,
        border: `1.5px solid ${p.fg}`,
        flexShrink: 0,
      }}
    />
  );
}
