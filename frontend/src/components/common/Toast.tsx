import { useJobStore, type ToastKind } from '../../stores/jobStore';

const KIND_COLORS: Record<ToastKind, { bg: string; border: string }> = {
  error: { bg: '#ef4444', border: '#dc2626' },
  success: { bg: '#22c55e', border: '#16a34a' },
  info: { bg: '#667eea', border: '#4f46e5' },
};

export function ToastContainer() {
  const toasts = useJobStore((s) => s.toasts);
  const dismissToast = useJobStore((s) => s.dismissToast);

  if (toasts.length === 0) return null;

  return (
    <div
      aria-live="polite"
      style={{
        position: 'fixed',
        top: '1rem',
        right: '1rem',
        zIndex: 2000,
        display: 'flex',
        flexDirection: 'column',
        gap: '0.5rem',
        maxWidth: 'min(90vw, 420px)',
      }}
    >
      {toasts.map((t) => {
        const c = KIND_COLORS[t.kind];
        return (
          <div
            key={t.id}
            role="status"
            style={{
              background: c.bg,
              color: '#fff',
              padding: '0.7rem 1rem',
              borderRadius: 8,
              boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
              border: `1px solid ${c.border}`,
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              gap: '0.75rem',
              fontSize: '0.9rem',
              lineHeight: 1.4,
            }}
          >
            <span style={{ flex: 1, wordBreak: 'break-word' }}>{t.message}</span>
            <button
              onClick={() => dismissToast(t.id)}
              aria-label="Dismiss"
              style={{
                background: 'transparent',
                border: 'none',
                color: '#fff',
                cursor: 'pointer',
                fontSize: '1rem',
                padding: 0,
                lineHeight: 1,
                flexShrink: 0,
              }}
            >
              X
            </button>
          </div>
        );
      })}
    </div>
  );
}
