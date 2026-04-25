import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useColors, useShadows } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space, z, motion } from '../../theme';
import { Button } from './Button';

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  /** Buttons rendered at the bottom-right. Typical: Cancel + primary action. */
  footer?: ReactNode;
  /** max-width of the modal panel. Defaults to 560px (form). */
  maxWidth?: number | string;
  /** If true, clicking the backdrop does NOT close the modal. */
  disableBackdropClose?: boolean;
}

export function Modal({ open, onClose, title, children, footer, maxWidth = 560, disableBackdropClose }: ModalProps) {
  const c = useColors();
  const s = useShadows();
  const panelRef = useRef<HTMLDivElement>(null);
  const lastFocusedBeforeOpen = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    lastFocusedBeforeOpen.current = (document.activeElement as HTMLElement | null) ?? null;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      } else if (e.key === 'Tab' && panelRef.current) {
        trapFocus(e, panelRef.current);
      }
    };
    document.addEventListener('keydown', onKey);

    // focus the first focusable element inside the panel
    requestAnimationFrame(() => {
      const first = panelRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      first?.focus();
    });

    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
      lastFocusedBeforeOpen.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  const backdropStyle: CSSProperties = {
    position: 'fixed',
    inset: 0,
    background: 'rgba(20, 17, 14, 0.55)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: space['4'],
    zIndex: z.modal,
    animation: `pratidhvani-fade-in ${motion.duration.base}ms ${motion.easing.standard}`,
  };

  const panelStyle: CSSProperties = {
    background: c.surface,
    color: c.textPrimary,
    border: `1px solid ${c.border}`,
    borderRadius: radius.lg,
    boxShadow: s.floating,
    width: '100%',
    maxWidth,
    maxHeight: 'calc(100vh - 3rem)',
    display: 'flex',
    flexDirection: 'column',
  };

  const headerStyle: CSSProperties = {
    padding: `${space['4']} ${space['5']}`,
    borderBottom: title ? `1px solid ${c.border}` : 'none',
    fontFamily: fonts.display,
    fontSize: fontSize.xl,
    fontWeight: fontWeight.semibold,
    color: c.textPrimary,
  };

  const bodyStyle: CSSProperties = {
    padding: space['5'],
    overflowY: 'auto',
    color: c.textPrimary,
    fontFamily: fonts.ui,
    fontSize: fontSize.base,
    lineHeight: 1.55,
  };

  const footerStyle: CSSProperties = {
    padding: `${space['3']} ${space['5']}`,
    borderTop: `1px solid ${c.border}`,
    display: 'flex',
    justifyContent: 'flex-end',
    gap: space['2'],
  };

  return createPortal(
    <div
      role="presentation"
      style={backdropStyle}
      onClick={(e) => {
        if (disableBackdropClose) return;
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? 'pratidhvani-modal-title' : undefined}
        style={panelStyle}
      >
        {title && (
          <div id="pratidhvani-modal-title" style={headerStyle}>
            {title}
          </div>
        )}
        <div style={bodyStyle}>{children}</div>
        {footer !== undefined && (
          <div style={footerStyle}>
            {footer ?? (
              <Button variant="secondary" onClick={onClose}>
                Close
              </Button>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

const FOCUSABLE_SELECTOR =
  'a[href], area[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), iframe, object, embed, [tabindex]:not([tabindex="-1"]), [contenteditable]';

function trapFocus(e: KeyboardEvent, container: HTMLElement) {
  const focusables = Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
    .filter((el) => !el.hasAttribute('disabled') && el.tabIndex !== -1);
  if (focusables.length === 0) {
    e.preventDefault();
    return;
  }
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  const active = document.activeElement as HTMLElement | null;
  if (e.shiftKey && active === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && active === last) {
    e.preventDefault();
    first.focus();
  }
}
