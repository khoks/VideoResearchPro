import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { useColors, useShadows } from '../../hooks/useTheme';
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from '../../hooks/useNotifications';
import { parseUtc } from '../../utils/cadence';
import type { AppNotification } from '../../services/notificationsApi';
import { fonts, fontSize, fontWeight, lineHeight, radius, space, target } from '../../theme';

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - parseUtc(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return parseUtc(iso).toLocaleDateString(undefined, { dateStyle: 'medium' });
}

function BellIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}

/**
 * The bell (S-8.3.3): unread count on the button, the latest notices in a
 * panel. Opening a notice marks it read and goes to its page; "Mark all
 * read" clears the count. Escape or a click outside closes the panel and
 * focus returns to the bell. The panel is portalled to <body> with fixed
 * coordinates: the sidebar is `position: sticky`, which makes it its own
 * stacking context, so a panel inside it would be painted under the page.
 */
export function NotificationBell({ align = 'left' }: { align?: 'left' | 'right' }) {
  const c = useColors();
  const s = useShadows();
  const navigate = useNavigate();
  const { data } = useNotifications();
  const markRead = useMarkNotificationRead();
  const markAll = useMarkAllNotificationsRead();
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const [place, setPlace] = useState<CSSProperties>({});

  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const r = buttonRef.current?.getBoundingClientRect();
      if (!r) return;
      const width = Math.min(340, window.innerWidth - 32);
      const left = align === 'right' ? r.right - width : r.left;
      setPlace({ top: r.bottom + 4, left: Math.max(16, Math.min(left, window.innerWidth - width - 16)), width });
    };
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [open, align]);
  const unread = data?.unread ?? 0;
  const items = data?.items ?? [];

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!panelRef.current?.contains(t) && !buttonRef.current?.contains(t)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    panelRef.current?.querySelector<HTMLElement>('button, a')?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, [open]);

  const openItem = (n: AppNotification) => {
    if (!n.read_at) markRead.mutate(n.id);
    setOpen(false);
    if (n.href) navigate(n.href);
  };

  return (
    <div style={{ position: 'relative' }}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        style={{
          position: 'relative',
          width: target.primary,
          height: target.primary,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: open ? c.surfaceAlt : 'transparent',
          border: 'none',
          borderRadius: radius.md,
          color: c.textSecondary,
          cursor: 'pointer',
          flexShrink: 0,
        }}
      >
        <BellIcon />
        {unread > 0 && (
          <span
            aria-hidden="true"
            style={{
              position: 'absolute',
              top: 6,
              right: 4,
              minWidth: 16,
              height: 16,
              padding: '0 4px',
              borderRadius: radius.pill,
              background: c.accent,
              color: c.textInverted,
              fontFamily: fonts.ui,
              fontSize: 10,
              fontWeight: fontWeight.semibold,
              lineHeight: '16px',
              textAlign: 'center',
            }}
          >
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && createPortal(
        <div
          ref={panelRef}
          id={panelId}
          role="dialog"
          aria-label="Notifications"
          style={{
            position: 'fixed',
            ...place,
            maxHeight: '70vh',
            overflowY: 'auto',
            background: c.surface,
            border: `1px solid ${c.border}`,
            borderRadius: radius.md,
            boxShadow: s.floating,
            zIndex: 200,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: `${space['2']} ${space['3']}`, borderBottom: `1px solid ${c.border}` }}>
            <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.textPrimary }}>Notifications</span>
            {unread > 0 && (
              <button
                type="button"
                onClick={() => markAll.mutate()}
                style={{ background: 'none', border: 'none', color: c.accent, fontFamily: fonts.ui, fontSize: fontSize.xs, cursor: 'pointer', minHeight: 32 }}
              >
                Mark all read
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <p style={{ margin: 0, padding: space['4'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>
              Nothing new. A saved search tells you here when its answer changes.
            </p>
          ) : (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {items.map((n) => (
                <li key={n.id} style={{ borderBottom: `1px solid ${c.border}` }}>
                  <button
                    type="button"
                    onClick={() => openItem(n)}
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      background: n.read_at ? 'transparent' : c.accentSubtle,
                      border: 'none',
                      padding: `${space['2']} ${space['3']}`,
                      cursor: 'pointer',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 2,
                    }}
                  >
                    <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: n.read_at ? fontWeight.regular : fontWeight.semibold, color: c.textPrimary, lineHeight: lineHeight.snug }}>
                      {n.title}
                      {!n.read_at && <span className="reader-sr-only"> (unread)</span>}
                    </span>
                    {n.body && (
                      <span style={{ fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.snug }}>{n.body}</span>
                    )}
                    <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>{ago(n.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}
