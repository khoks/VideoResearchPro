import { useState, type CSSProperties } from 'react';
import { useColors, useShadows } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space, z } from '../../theme';
import type { Tier } from '../../hooks/useMe';

interface MockPaymentModalProps {
  open: boolean;
  targetTier: Tier;
  targetTierName: string;
  targetTierPrice: string;
  onClose: () => void;
  onConfirm: () => void;
  loading?: boolean;
}

/**
 * Mock payment modal — demo-mode UI for the self-service tier flip flow.
 *
 * Renders a Stripe-style card form pre-filled with test-card values,
 * with a prominent "Demo mode — no real payment processed" banner. The
 * "Pay" button calls `onConfirm`, which the parent uses to fire the
 * `PUT /auth/me/tier` request.
 *
 * Per D-050, the form values are NOT sent to the backend today —
 * they're cosmetic, exercising the UX of a real payment flow so the
 * shape doesn't surprise anyone when E-5.3 (Stripe) lands.
 */
export function MockPaymentModal({
  open,
  targetTier,
  targetTierName,
  targetTierPrice,
  onClose,
  onConfirm,
  loading,
}: MockPaymentModalProps) {
  const c = useColors();
  const s = useShadows();
  const [cardNumber, setCardNumber] = useState('4242 4242 4242 4242');
  const [expiry, setExpiry] = useState('12 / 30');
  const [cvc, setCvc] = useState('123');
  const [name, setName] = useState('Demo User');

  if (!open) return null;

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.45)',
        zIndex: z.modal,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: space['5'],
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Upgrade to ${targetTierName} (demo payment)`}
        style={{
          background: c.surface,
          color: c.textPrimary,
          border: `1px solid ${c.border}`,
          borderRadius: radius.lg,
          boxShadow: s.floating,
          width: '100%',
          maxWidth: 480,
          padding: `${space['6']} ${space['6']}`,
        }}
      >
        {/* Demo-mode banner */}
        <div
          style={{
            background: c.warnSubtle,
            color: c.warn,
            border: `1px solid ${c.warn}`,
            borderRadius: radius.sm,
            padding: `${space['2']} ${space['3']}`,
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            fontWeight: fontWeight.semibold,
            letterSpacing: '0.02em',
            marginBottom: space['5'],
          }}
        >
          DEMO MODE — no real payment will be processed.
        </div>

        <h2
          style={{
            margin: 0,
            fontFamily: fonts.display,
            fontSize: fontSize.xl,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
          }}
        >
          Upgrade to {targetTierName}
        </h2>
        <p
          style={{
            margin: `${space['2']} 0 ${space['5']}`,
            fontFamily: fonts.body,
            fontSize: fontSize.sm,
            color: c.textSecondary,
            lineHeight: lineHeight.normal,
          }}
        >
          You're subscribing to <strong>{targetTierName}</strong> for{' '}
          <strong>
            {targetTierPrice}
            {targetTier === 'free' ? '' : ' / month'}
          </strong>
          . Cancel any time from this page.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'], marginBottom: space['5'] }}>
          <Field label="Name on card" value={name} onChange={setName} />
          <Field label="Card number" value={cardNumber} onChange={setCardNumber} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: space['3'] }}>
            <Field label="Expiry" value={expiry} onChange={setExpiry} />
            <Field label="CVC" value={cvc} onChange={setCvc} />
          </div>
        </div>

        <div style={{ display: 'flex', gap: space['3'], justifyContent: 'flex-end' }}>
          <ActionButton variant="secondary" onClick={onClose} disabled={loading}>
            Cancel
          </ActionButton>
          <ActionButton variant="primary" onClick={onConfirm} disabled={loading}>
            {loading ? 'Processing…' : `Pay ${targetTierPrice}`}
          </ActionButton>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const c = useColors();
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: space['1'] }}>
      <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary, fontWeight: fontWeight.medium }}>
        {label}
      </span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          fontFamily: fonts.mono,
          fontSize: fontSize.sm,
          padding: `${space['2']} ${space['3']}`,
          background: c.bg,
          color: c.textPrimary,
          border: `1px solid ${c.border}`,
          borderRadius: radius.sm,
          outline: 'none',
        }}
      />
    </label>
  );
}

function ActionButton({
  variant,
  onClick,
  disabled,
  children,
}: {
  variant: 'primary' | 'secondary';
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const c = useColors();
  const [hovered, setHovered] = useState(false);
  const base: CSSProperties = {
    padding: `${space['2']} ${space['4']}`,
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    borderRadius: radius.md,
    cursor: disabled ? 'wait' : 'pointer',
    border: '1px solid',
    transition: 'all 120ms cubic-bezier(0.2, 0.8, 0.2, 1)',
  };
  const variants: Record<string, CSSProperties> = {
    primary: {
      background: hovered && !disabled ? c.borderStrong : c.accent,
      color: c.bg,
      borderColor: hovered && !disabled ? c.borderStrong : c.accent,
    },
    secondary: {
      background: hovered ? c.surfaceAlt : 'transparent',
      color: c.textPrimary,
      borderColor: c.border,
    },
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ ...base, ...variants[variant] }}
    >
      {children}
    </button>
  );
}
