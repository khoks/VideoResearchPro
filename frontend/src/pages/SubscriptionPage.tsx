import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import api from '../services/api';
import { useColors } from '../hooks/useTheme';
import { useMe, useInvalidateMe, type Tier } from '../hooks/useMe';
import { useJobStore } from '../stores/jobStore';
import { TIER_DESCRIPTORS, getTierDescriptor } from '../data/tiers';
import { TierCard } from '../components/marketing/TierCard';
import { MockPaymentModal } from '../components/marketing/MockPaymentModal';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../theme';

/**
 * In-app subscription manager. Authenticated users land here from the
 * sidebar "Account" group. Shows the same three tier cards as the public
 * pricing page, but with the current plan highlighted and action buttons
 * that route through a mock-payment modal → `PUT /auth/me/tier`.
 *
 * Downgrade (target tier rank < current) skips the payment modal and
 * shows a confirmation dialog listing the features the user will lose.
 *
 * D-050: no real payment is processed. When E-5.3 (Stripe) ships, the
 * `confirm` handler swaps the direct backend call for a Stripe Checkout
 * redirect; the rest of the UI is unchanged.
 */
export function SubscriptionPage() {
  const c = useColors();
  const { data: me, refetch } = useMe();
  const invalidateMe = useInvalidateMe();
  const pushToast = useJobStore((s) => s.pushToast);
  const [searchParams, setSearchParams] = useSearchParams();
  const [targetTier, setTargetTier] = useState<Tier | null>(null);
  const [confirmingDowngrade, setConfirmingDowngrade] = useState<Tier | null>(null);

  const currentTier: Tier = me?.tier ?? 'free';
  const currentDescriptor = getTierDescriptor(currentTier);

  // ?upgrade=<tier> deep-link from /pricing → open the right modal.
  useEffect(() => {
    const intent = searchParams.get('upgrade');
    if (intent && (intent === 'free' || intent === 'pro' || intent === 'studio')) {
      if (intent !== currentTier) {
        const isUpgrade = tierRank(intent) > tierRank(currentTier);
        if (isUpgrade) setTargetTier(intent);
        else setConfirmingDowngrade(intent);
      }
      searchParams.delete('upgrade');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, currentTier, setSearchParams]);

  const changeTier = useMutation({
    mutationFn: async (newTier: Tier) => {
      const { data } = await api.put<{ tier: Tier; message: string }>('/auth/me/tier', {
        tier: newTier,
        mock_payment: { card_number: '4242424242424242', cvc: '123', expiry: '12/30' },
      });
      return data;
    },
    onSuccess: async (data) => {
      await invalidateMe();
      await refetch();
      setTargetTier(null);
      setConfirmingDowngrade(null);
      pushToast(
        'success',
        `You're now on the ${data.tier.charAt(0).toUpperCase() + data.tier.slice(1)} plan. New features are active immediately.`,
      );
    },
  });

  const handleAction = (tier: Tier) => {
    if (tier === currentTier) return;
    const isUpgrade = tierRank(tier) > tierRank(currentTier);
    if (isUpgrade) {
      setTargetTier(tier);
    } else {
      setConfirmingDowngrade(tier);
    }
  };

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <header style={{ marginBottom: space['6'] }}>
        <h1
          style={{
            margin: 0,
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
          }}
        >
          Subscription
        </h1>
        <p
          style={{
            margin: `${space['2']} 0 0`,
            fontFamily: fonts.body,
            fontSize: fontSize.md,
            color: c.textSecondary,
            lineHeight: lineHeight.normal,
          }}
        >
          You're on the <strong>{currentDescriptor.name}</strong> plan. {currentDescriptor.tagline}
        </p>
      </header>

      {/* Demo-mode banner */}
      <div
        style={{
          background: c.warnSubtle,
          color: c.warn,
          border: `1px solid ${c.warn}`,
          borderRadius: radius.md,
          padding: `${space['3']} ${space['4']}`,
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          lineHeight: lineHeight.normal,
          marginBottom: space['6'],
        }}
      >
        <strong>Demo mode.</strong> No real payment is processed — tier upgrades are instant. When the
        SaaS launches the same flow plugs into Stripe (E-5.3). Use this to evaluate Pro / Studio features
        on your self-host today.
      </div>

      {/* Tier grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: space['5'],
          alignItems: 'stretch',
        }}
      >
        {TIER_DESCRIPTORS.map((td) => {
          const isCurrent = td.tier === currentTier;
          const isRecommended = !isCurrent && td.tier === 'pro' && currentTier !== 'studio';
          const actionLabel = isCurrent
            ? undefined
            : tierRank(td.tier) > tierRank(currentTier)
            ? `Upgrade to ${td.name}`
            : `Downgrade to ${td.name}`;
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
              actionLoading={changeTier.isPending && targetTier === td.tier}
              actionVariant={isRecommended || tierRank(td.tier) > tierRank(currentTier) ? 'primary' : 'secondary'}
            />
          );
        })}
      </div>

      {/* Upgrade flow → mock payment modal */}
      {targetTier && (
        <MockPaymentModal
          open
          targetTier={targetTier}
          targetTierName={getTierDescriptor(targetTier).name}
          targetTierPrice={getTierDescriptor(targetTier).price}
          onClose={() => {
            if (!changeTier.isPending) setTargetTier(null);
          }}
          onConfirm={() => changeTier.mutate(targetTier)}
          loading={changeTier.isPending}
        />
      )}

      {/* Downgrade confirmation modal — no payment step */}
      {confirmingDowngrade && (
        <DowngradeConfirmModal
          fromTier={currentTier}
          toTier={confirmingDowngrade}
          onClose={() => setConfirmingDowngrade(null)}
          onConfirm={() => changeTier.mutate(confirmingDowngrade)}
          loading={changeTier.isPending}
        />
      )}
    </div>
  );
}

function DowngradeConfirmModal({
  fromTier,
  toTier,
  onClose,
  onConfirm,
  loading,
}: {
  fromTier: Tier;
  toTier: Tier;
  onClose: () => void;
  onConfirm: () => void;
  loading?: boolean;
}) {
  const c = useColors();
  const lostFeatures = featuresLostOnDowngrade(fromTier, toTier);

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.45)',
        zIndex: 300,
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
        aria-label={`Downgrade to ${toTier}`}
        style={{
          background: c.surface,
          color: c.textPrimary,
          border: `1px solid ${c.border}`,
          borderRadius: radius.lg,
          width: '100%',
          maxWidth: 480,
          padding: `${space['6']} ${space['6']}`,
        }}
      >
        <h2 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.xl, color: c.textPrimary }}>
          Confirm downgrade
        </h2>
        <p style={{ margin: `${space['3']} 0 ${space['4']}`, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal }}>
          You're downgrading from <strong>{getTierDescriptor(fromTier).name}</strong> to{' '}
          <strong>{getTierDescriptor(toTier).name}</strong>. You'll lose access to:
        </p>
        {lostFeatures.length > 0 ? (
          <ul
            style={{
              paddingLeft: space['5'],
              fontFamily: fonts.body,
              fontSize: fontSize.sm,
              color: c.textPrimary,
              lineHeight: lineHeight.normal,
              margin: 0,
            }}
          >
            {lostFeatures.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        ) : (
          <p style={{ fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textMuted, fontStyle: 'italic' }}>
            (No premium features to lose.)
          </p>
        )}
        <div style={{ display: 'flex', gap: space['3'], justifyContent: 'flex-end', marginTop: space['5'] }}>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            style={{
              padding: `${space['2']} ${space['4']}`,
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              fontWeight: fontWeight.semibold,
              background: 'transparent',
              color: c.textPrimary,
              border: `1px solid ${c.border}`,
              borderRadius: radius.md,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            style={{
              padding: `${space['2']} ${space['4']}`,
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              fontWeight: fontWeight.semibold,
              background: c.accent,
              color: c.bg,
              border: `1px solid ${c.accent}`,
              borderRadius: radius.md,
              cursor: loading ? 'wait' : 'pointer',
            }}
          >
            {loading ? 'Processing…' : `Downgrade to ${getTierDescriptor(toTier).name}`}
          </button>
        </div>
      </div>
    </div>
  );
}

function tierRank(t: Tier): number {
  return t === 'free' ? 0 : t === 'pro' ? 1 : 2;
}

function featuresLostOnDowngrade(from: Tier, to: Tier): string[] {
  const fromFeatures = new Set(getTierDescriptor(from).features.filter((f) => f.included).map((f) => f.label));
  const toFeatures = new Set(getTierDescriptor(to).features.filter((f) => f.included).map((f) => f.label));
  return [...fromFeatures].filter((f) => !toFeatures.has(f) && f !== 'Everything in Free' && f !== 'Everything in Pro');
}
