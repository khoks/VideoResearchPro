/**
 * Bottom reading toolbar for screens where the outline column is hidden
 * (< 1200 px; S-8.12.1, ui-design §2.4): Contents (the outline as a bottom
 * sheet), text size, theme, and the reading percentage. Every control is a
 * 44 px target; the bar sits above the home indicator via
 * `env(safe-area-inset-bottom)`. CSS hides it on wide screens, where the
 * sticky outline and the progress pill do the same jobs.
 */
import { useEffect, useRef, useState, type MouseEvent, type ReactNode, type Ref } from 'react';
import { useColors, useShadows } from '../../hooks/useTheme';
import { useJobStore } from '../../stores/jobStore';
import { readerScaleFor, useReaderStore } from '../../stores/readerStore';
import { fonts, fontSize, fontWeight, lineHeight, radius, readerScale, space, target, z } from '../../theme';
import type { OutlineEntry } from './parseReport';

interface ReaderToolbarProps {
  outline: OutlineEntry[];
  activeId: string | null;
  progress: number;
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

export function ReaderToolbar({ outline, activeId, progress }: ReaderToolbarProps) {
  const c = useColors();
  const theme = useJobStore((s) => s.theme);
  const toggleTheme = useJobStore((s) => s.toggleTheme);
  const { step, smaller, larger } = useReaderStore();
  const [sheetOpen, setSheetOpen] = useState(false);
  const contentsButton = useRef<HTMLButtonElement | null>(null);
  const pct = Math.round(progress * 100);
  const scale = readerScaleFor(step);

  return (
    <>
      <div
        className="reader-toolbar reader-no-print"
        role="toolbar"
        aria-label="Reading controls"
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: z.sticky,
          display: 'flex',
          alignItems: 'center',
          gap: space['1'],
          padding: `${space['1']} ${space['3']}`,
          paddingBottom: `calc(${space['1']} + env(safe-area-inset-bottom))`,
          paddingLeft: `max(${space['3']}, env(safe-area-inset-left))`,
          paddingRight: `max(${space['3']}, env(safe-area-inset-right))`,
          background: c.surface,
          borderTop: `1px solid ${c.border}`,
          fontFamily: fonts.ui,
        }}
      >
        {outline.length > 0 && (
          <ToolButton
            ref={contentsButton}
            onClick={() => setSheetOpen(true)}
            aria-haspopup="dialog"
            aria-expanded={sheetOpen}
          >
            Contents
          </ToolButton>
        )}
        <ToolButton onClick={smaller} disabled={step === 0} aria-label="Smaller text">
          <span aria-hidden style={{ fontSize: fontSize.sm }}>A−</span>
        </ToolButton>
        <ToolButton onClick={larger} disabled={step === readerScale.length - 1} aria-label="Larger text">
          <span aria-hidden style={{ fontSize: fontSize.lg }}>A+</span>
        </ToolButton>
        <ToolButton
          onClick={toggleTheme}
          aria-label={theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}
        >
          {theme === 'light' ? 'Dark' : 'Light'}
        </ToolButton>
        <span
          aria-live="off"
          style={{ marginLeft: 'auto', fontSize: fontSize.xs, color: c.textMuted, whiteSpace: 'nowrap' }}
        >
          <span className="reader-sr-only">Text size {Math.round(scale * 100)}%. </span>
          {pct}%
        </span>
      </div>
      {sheetOpen && (
        <ContentsSheet
          outline={outline}
          activeId={activeId}
          onClose={() => {
            setSheetOpen(false);
            contentsButton.current?.focus();
          }}
        />
      )}
    </>
  );
}

interface ToolButtonProps {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  'aria-label'?: string;
  'aria-haspopup'?: 'dialog';
  'aria-expanded'?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

function ToolButton({ children, onClick, disabled, ref, ...aria }: ToolButtonProps) {
  const c = useColors();
  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="reader-tool"
      {...aria}
      style={{
        minWidth: target.primary,
        minHeight: target.primary,
        padding: `0 ${space['3']}`,
        border: 'none',
        borderRadius: radius.md,
        background: 'transparent',
        color: disabled ? c.textMuted : c.textPrimary,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        fontWeight: fontWeight.medium,
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {children}
    </button>
  );
}

function ContentsSheet({
  outline,
  activeId,
  onClose,
}: {
  outline: OutlineEntry[];
  activeId: string | null;
  onClose: () => void;
}) {
  const c = useColors();
  const s = useShadows();
  const panel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const first =
      panel.current?.querySelector<HTMLAnchorElement>('a[aria-current="true"]') ??
      panel.current?.querySelector<HTMLAnchorElement>('a');
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const jump = (e: MouseEvent<HTMLAnchorElement>, id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    e.preventDefault();
    onClose();
    // After the sheet unmounts, so focus lands on the heading, not the button.
    requestAnimationFrame(() => {
      el.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
      el.focus({ preventScroll: true });
      window.history.replaceState(null, '', `#${id}`);
    });
  };

  return (
    <div
      className="reader-no-print"
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: z.modal, background: 'rgba(20, 17, 14, 0.45)' }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label="Contents"
        onClick={(e) => e.stopPropagation()}
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          maxHeight: '75dvh',
          overflowY: 'auto',
          overscrollBehavior: 'contain',
          background: c.surface,
          borderTopLeftRadius: radius.lg,
          borderTopRightRadius: radius.lg,
          boxShadow: s.floating,
          padding: `${space['3']} ${space['4']}`,
          paddingBottom: `calc(${space['4']} + env(safe-area-inset-bottom))`,
          fontFamily: fonts.ui,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: space['2'] }}>
          <p
            style={{
              margin: 0,
              fontSize: fontSize.xs,
              fontWeight: fontWeight.semibold,
              color: c.textMuted,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
            }}
          >
            Contents
          </p>
          <ToolButton onClick={onClose} aria-label="Close contents">
            Close
          </ToolButton>
        </div>
        <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {outline.map((entry) => {
            const active = entry.id === activeId;
            return (
              <li key={entry.id}>
                <a
                  href={`#${entry.id}`}
                  aria-current={active ? 'true' : undefined}
                  onClick={(e) => jump(e, entry.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    minHeight: target.primary,
                    padding: `${space['1']} ${space['3']}`,
                    paddingLeft: entry.level === 3 ? space['6'] : space['3'],
                    borderLeft: `2px solid ${active ? c.accent : 'transparent'}`,
                    color: active ? c.accent : c.textPrimary,
                    fontSize: entry.level === 3 ? fontSize.sm : fontSize.base,
                    fontWeight: active ? fontWeight.semibold : fontWeight.regular,
                    lineHeight: lineHeight.snug,
                    textDecoration: 'none',
                  }}
                >
                  {entry.text}
                </a>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
