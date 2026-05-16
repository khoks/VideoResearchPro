import { useNavigate } from 'react-router-dom';
import { useColors } from '../../hooks/useTheme';
import { useAuth } from '../../contexts/AuthContext';
import { useMe } from '../../hooks/useMe';
import { TIER_DESCRIPTORS } from '../../data/tiers';
import { TierCard } from '../../components/marketing/TierCard';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';

/**
 * Public-facing pricing page — three-column tier grid.
 *
 * When logged out: each card's action navigates to `/register?intent=<tier>`.
 * When logged in: the user's current tier is highlighted; other tiers
 * deep-link into `/account/subscription` for the actual upgrade flow.
 */
export function PricingPage() {
  const c = useColors();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const { data: me } = useMe();
  const currentTier = me?.tier ?? null;

  const handleAction = (tier: 'free' | 'pro' | 'studio') => {
    if (!isAuthenticated) {
      navigate(`/register?intent=${tier}`);
      return;
    }
    if (tier === currentTier) return;
    navigate(`/account/subscription?upgrade=${tier}`);
  };

  return (
    <div style={{ background: c.bg, color: c.textPrimary }}>
      <section
        style={{
          maxWidth: 1100,
          margin: '0 auto',
          padding: `${space['8']} ${space['5']} ${space['5']}`,
          textAlign: 'center',
        }}
      >
        <h1
          style={{
            margin: 0,
            fontFamily: fonts.display,
            fontSize: fontSize['3xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            lineHeight: lineHeight.tight,
          }}
        >
          Simple, honest pricing.
        </h1>
        <p
          style={{
            margin: `${space['3']} auto 0`,
            maxWidth: 640,
            fontFamily: fonts.body,
            fontStyle: 'italic',
            fontSize: fontSize.md,
            color: c.textSecondary,
          }}
        >
          Free tier covers the full research loop. Pro unlocks the Author Studio.
          Studio unlocks Echo — the personal-brain agent.
        </p>
      </section>

      <section
        style={{
          maxWidth: 1100,
          margin: '0 auto',
          padding: `${space['5']} ${space['5']} ${space['8']}`,
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: space['5'],
          alignItems: 'stretch',
        }}
      >
        {TIER_DESCRIPTORS.map((td) => {
          const isCurrent = currentTier === td.tier;
          // Recommend Pro for everyone except current-Pro and current-Studio users.
          const isRecommended = !isCurrent && td.tier === 'pro' && currentTier !== 'studio';
          const actionLabel = !isAuthenticated
            ? td.tier === 'free'
              ? 'Get started free'
              : `Sign up for ${td.name}`
            : isCurrent
            ? undefined
            : `Switch to ${td.name}`;
          return (
            <TierCard
              key={td.tier}
              tier={td.tier}
              name={td.name}
              price={td.price}
              priceCadence={td.priceCadence ?? '/month'}
              tagline={td.tagline}
              features={td.features}
              current={isCurrent}
              recommended={isRecommended}
              onAction={isCurrent ? undefined : () => handleAction(td.tier)}
              actionLabel={actionLabel}
              actionVariant={isRecommended || !isCurrent ? 'primary' : 'secondary'}
            />
          );
        })}
      </section>

      <section
        style={{
          maxWidth: 720,
          margin: '0 auto',
          padding: `${space['5']} ${space['5']} ${space['10']}`,
          textAlign: 'center',
          fontFamily: fonts.body,
          fontSize: fontSize.sm,
          color: c.textMuted,
          lineHeight: lineHeight.normal,
        }}
      >
        <p style={{ margin: 0 }}>
          Self-host today. SaaS soon. Cancel any time.
        </p>
        <p style={{ margin: `${space['2']} 0 0`, fontStyle: 'italic' }}>
          (Demo mode: tier upgrades happen instantly without real payment. When the SaaS launches,
          the same flow plugs into Stripe — the same UI, the same shape, just a real payment in the middle.)
        </p>
      </section>
    </div>
  );
}
