import { useJobStore, type ToastKind } from '../../stores/jobStore';
import { useColors, useShadows } from '../../hooks/useTheme';
import type { ResolvedColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space, z } from '../../theme';

function paletteFor(kind: ToastKind, c: ResolvedColors) {
  switch (kind) {
    case 'error':   return { bg: c.errorSubtle,   border: c.error,   text: c.error };
    case 'success': return { bg: c.successSubtle, border: c.success, text: c.success };
    case 'info':    return { bg: c.infoSubtle,    border: c.info,    text: c.info };
  }
}

export function ToastContainer() {
  const toasts = useJobStore((s) => s.toasts);
  const dismissToast = useJobStore((s) => s.dismissToast);
  const c = useColors();
  const s = useShadows();

  if (toasts.length === 0) return null;

  return (
    <div
      aria-live="polite"
      style={{
        position: 'fixed',
        top: space['4'],
        right: space['4'],
        zIndex: z.toast,
        display: 'flex',
        flexDirection: 'column',
        gap: space['2'],
        maxWidth: 'min(90vw, 420px)',
      }}
    >
      {toasts.map((t) => {
        const p = paletteFor(t.kind, c);
        return (
          <div
            key={t.id}
            role="status"
            style={{
              background: p.bg,
              color: p.text,
              padding: `${space['3']} ${space['4']}`,
              borderRadius: radius.md,
              boxShadow: s.floating,
              border: `1px solid ${p.border}`,
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              gap: space['3'],
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              lineHeight: lineHeight.snug,
            }}
          >
            <span style={{ flex: 1, wordBreak: 'break-word' }}>{t.message}</span>
            <button
              onClick={() => dismissToast(t.id)}
              aria-label="Dismiss"
              style={{
                background: 'transparent',
                border: 'none',
                color: p.text,
                cursor: 'pointer',
                fontSize: fontSize.md,
                fontWeight: fontWeight.medium,
                padding: 0,
                lineHeight: 1,
                flexShrink: 0,
              }}
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}
