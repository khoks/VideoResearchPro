import { useState, type CSSProperties, type ReactNode } from 'react';
import { useColors, useShadows } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import type { Tier } from '../../hooks/useMe';

export interface TierFeature {
  label: string;
  included: boolean;
  /** When provided, shown in a tooltip on hover. */
  detail?: string;
}

export interface TierCardProps {
  tier: Tier;
  /** Display name — "Free", "Pro", "Studio". */
  name: string;
  /** Monthly price string — "$0", "$19", "$49". Free shows "$0" + "forever". */
  price: string;
  priceCadence?: string;
  tagline: string;
  features: TierFeature[];
  /** When true, renders a "Current plan" pill instead of the action button. */
  current?: boolean;
  /** When true, highlights this card visually as the recommended option. */
  recommended?: boolean;
  /** Click handler for the action button. Pass `undefined` to render no button. */
  onAction?: () => void;
  /** Action button label — defaults to "Choose <name>". */
  actionLabel?: string;
  /** Visual variant of the action button. */
  actionVariant?: 'primary' | 'secondary';
  /** When true, the action button is disabled (loading state). */
  actionLoading?: boolean;
}

/**
 * Shared tier card used by the public pricing page AND the in-app
 * subscription page. Warm-editorial: paper card, ink-line borders,
 * generous spacing. Highlighted state for the user's current tier and
 * for the "Recommended" tier on the public pricing page.
 */
export function TierCard({
  name,
  price,
  priceCadence = '/month',
  tagline,
  features,
  current,
  recommended,
  onAction,
  actionLabel,
  actionVariant = 'primary',
  actionLoading,
}: TierCardProps) {
  const c = useColors();
  const s = useShadows();
  const [hovered, setHovered] = useState(false);

  const borderColor = current
    ? c.accent
    : recommended
    ? c.gold
    : c.border;

  return (
    <div
      style={{
        background: c.surface,
        border: `${current || recommended ? 2 : 1}px solid ${borderColor}`,
        borderRadius: radius.lg,
        padding: `${space['6']} ${space['5']}`,
        display: 'flex',
        flexDirection: 'column',
        gap: space['5'],
        minHeight: 520,
        boxShadow: current || recommended ? s.floating : 'none',
        position: 'relative',
      }}
    >
      {recommended && !current && (
        <div
          style={{
            position: 'absolute',
            top: -12,
            right: space['4'],
            background: c.gold,
            color: c.bg,
            padding: `${space['1']} ${space['3']}`,
            borderRadius: radius.pill,
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            fontWeight: fontWeight.semibold,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
          }}
        >
          Recommended
        </div>
      )}
      {current && (
        <div
          style={{
            position: 'absolute',
            top: -12,
            right: space['4'],
            background: c.accent,
            color: c.bg,
            padding: `${space['1']} ${space['3']}`,
            borderRadius: radius.pill,
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            fontWeight: fontWeight.semibold,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
          }}
        >
          Current plan
        </div>
      )}

      <div>
        <h3
          style={{
            margin: 0,
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
          }}
        >
          {name}
        </h3>
        <p
          style={{
            margin: `${space['2']} 0 0`,
            fontFamily: fonts.body,
            fontStyle: 'italic',
            fontSize: fontSize.sm,
            color: c.textSecondary,
            lineHeight: lineHeight.snug,
            minHeight: '2.5em',
          }}
        >
          {tagline}
        </p>
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: space['2'] }}>
        <span
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize['3xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            lineHeight: 1,
          }}
        >
          {price}
        </span>
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>
          {priceCadence}
        </span>
      </div>

      <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: space['2'], flex: 1 }}>
        {features.map((f, idx) => (
          <FeatureRow key={idx} feature={f} />
        ))}
      </ul>

      {onAction && (
        <TierActionButton
          label={actionLabel ?? `Choose ${name}`}
          variant={actionVariant}
          onClick={onAction}
          loading={actionLoading}
          hovered={hovered}
          setHovered={setHovered}
        />
      )}
    </div>
  );
}

function FeatureRow({ feature }: { feature: TierFeature }) {
  const c = useColors();
  return (
    <li
      title={feature.detail}
      style={{
        display: 'flex',
        gap: space['2'],
        alignItems: 'flex-start',
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        color: feature.included ? c.textPrimary : c.textMuted,
        textDecoration: feature.included ? 'none' : 'line-through',
        textDecorationColor: c.textMuted,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 16,
          flexShrink: 0,
          color: feature.included ? c.forest : c.textMuted,
          fontWeight: fontWeight.semibold,
          lineHeight: lineHeight.normal,
        }}
      >
        {feature.included ? '✓' : '−'}
      </span>
      <span style={{ lineHeight: lineHeight.normal }}>{feature.label}</span>
    </li>
  );
}

function TierActionButton({
  label,
  variant,
  onClick,
  loading,
  hovered,
  setHovered,
}: {
  label: ReactNode;
  variant: 'primary' | 'secondary';
  onClick: () => void;
  loading?: boolean;
  hovered: boolean;
  setHovered: (v: boolean) => void;
}) {
  const c = useColors();
  const [focused, setFocused] = useState(false);

  const base: CSSProperties = {
    width: '100%',
    padding: `${space['3']} ${space['5']}`,
    fontFamily: fonts.ui,
    fontSize: fontSize.base,
    fontWeight: fontWeight.semibold,
    borderRadius: radius.md,
    cursor: loading ? 'wait' : 'pointer',
    border: '1px solid',
    transition: 'all 120ms cubic-bezier(0.2, 0.8, 0.2, 1)',
    outline: focused ? `2px solid ${c.focus}` : 'none',
    outlineOffset: 2,
  };

  const stylesByVariant: Record<'primary' | 'secondary', CSSProperties> = {
    primary: {
      background: hovered ? c.borderStrong : c.accent,
      color: c.bg,
      borderColor: hovered ? c.borderStrong : c.accent,
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
      disabled={loading}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={{ ...base, ...stylesByVariant[variant] }}
    >
      {loading ? 'Processing…' : label}
    </button>
  );
}
