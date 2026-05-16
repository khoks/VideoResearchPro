/*
 * Tier display content — names, prices, taglines, feature lists.
 *
 * Single source of truth for the pricing page (`PricingPage`) and the
 * in-app subscription manager (`SubscriptionPage`). Adjust labels here;
 * the actual capabilities are enforced by `backend/app/services/tier_service.py`
 * and mirrored on the frontend by `useTierCapabilities.ts`.
 */

import type { Tier } from '../hooks/useMe';
import type { TierFeature } from '../components/marketing/TierCard';

export interface TierDescriptor {
  tier: Tier;
  name: string;
  price: string;
  priceCadence?: string;
  tagline: string;
  /** Short single-line elevator pitch for the marketing landing hero. */
  oneLiner: string;
  /** Feature checklist shown on the card. */
  features: TierFeature[];
}

export const TIER_DESCRIPTORS: TierDescriptor[] = [
  {
    tier: 'free',
    name: 'Free',
    price: '$0',
    priceCadence: 'forever',
    tagline: 'Build your personal library at your own pace.',
    oneLiner: 'Everything you need to ingest a few hundred sources and ask citation-grounded questions.',
    features: [
      { label: 'Topic, channel, and subscription jobs', included: true },
      { label: 'Library-wide Q&A with citations', included: true },
      { label: 'Q&A history meta-chat', included: true },
      { label: 'Per-video knowledge artifacts', included: true },
      { label: 'Dataset exports (Q&A + knowledge)', included: true },
      { label: 'Up to 500 documents in your library', included: true },
      { label: 'Up to 50 Q&A exchanges / month', included: true },
      { label: 'Author Studio (books, sites, decks)', included: false },
      { label: 'BYOK — bring your own LLM provider', included: false },
      { label: 'Echo personal-brain agent', included: false },
    ],
  },
  {
    tier: 'pro',
    name: 'Pro',
    price: '$19',
    tagline: 'Bigger library, output generation, and shelves.',
    oneLiner: 'Author Studio + 10× quotas. Generate books and curated collections from your sources.',
    features: [
      { label: 'Everything in Free', included: true },
      { label: 'Author Studio — books, sites, decks, reels', included: true, detail: 'Generate long-form output from your library' },
      { label: 'Shelves — group jobs into projects', included: true },
      { label: 'Saved searches with alerts', included: true },
      { label: 'Public report sharing (signed URLs)', included: true },
      { label: 'Up to 5,000 documents', included: true },
      { label: 'Up to 1,000 Q&A exchanges / month', included: true },
      { label: '2M LLM tokens / day', included: true },
      { label: 'BYOK — bring your own LLM provider', included: false },
      { label: 'Echo personal-brain agent', included: false },
    ],
  },
  {
    tier: 'studio',
    name: 'Studio',
    price: '$49',
    tagline: 'The full personal brain. Unlimited library. Your voice.',
    oneLiner: 'Echo personal-brain, BYOK keys, unlimited library. The full vision of Pratidhvani.',
    features: [
      { label: 'Everything in Pro', included: true },
      { label: 'Echo — personal-brain agent (Studio-only)', included: true, detail: 'Learns your voice and speaks as you' },
      { label: 'BYOK — use your own OpenAI / Anthropic / Google keys', included: true },
      { label: 'Team workspaces', included: true },
      { label: 'Data residency selection', included: true },
      { label: 'Unlimited documents', included: true },
      { label: 'Unlimited Q&A exchanges', included: true },
      { label: '10M LLM tokens / day', included: true },
      { label: 'Priority support', included: true },
      { label: 'Early access to new connectors', included: true },
    ],
  },
];

export function getTierDescriptor(tier: Tier): TierDescriptor {
  return TIER_DESCRIPTORS.find((t) => t.tier === tier) ?? TIER_DESCRIPTORS[0];
}
