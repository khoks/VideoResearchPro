/*
 * Tier capability resolution on the frontend.
 *
 * This is a MIRROR of `backend/app/services/tier_service.py::TIER_CAPABILITIES`.
 * Keep the two in sync by convention — if you add a feature to the backend
 * registry, add it here too. Drift is caught by feature-gate 403s at runtime
 * (and ideally by a future contract test, but that's not in place yet).
 *
 * The backend remains authoritative — these flags are for UI gating only
 * (showing/hiding nav items, "Coming soon" stubs). Every actual mutation
 * goes through `require_feature(...)` at the API layer.
 */

import { useMe, type Tier } from './useMe';

export type Feature =
  | 'topic_jobs'
  | 'channel_jobs'
  | 'subscription_jobs'
  | 'library_qa'
  | 'qa_history_chat'
  | 'knowledge_extract'
  | 'author_studio'
  | 'shelves'
  | 'saved_searches'
  | 'public_report_sharing'
  | 'byok_llm_keys'
  | 'team_workspace'
  | 'data_residency_choice'
  | 'echo_personal_brain'
  | 'echo_speak_as_me';

const FREE_FEATURES: ReadonlyArray<Feature> = [
  'topic_jobs',
  'channel_jobs',
  'subscription_jobs',
  'library_qa',
  'qa_history_chat',
  'knowledge_extract',
];

const PRO_FEATURES: ReadonlyArray<Feature> = [
  ...FREE_FEATURES,
  'author_studio',
  'shelves',
  'saved_searches',
  'public_report_sharing',
];

const STUDIO_FEATURES: ReadonlyArray<Feature> = [
  ...PRO_FEATURES,
  'byok_llm_keys',
  'team_workspace',
  'data_residency_choice',
  'echo_personal_brain',
  'echo_speak_as_me',
];

const FEATURES_BY_TIER: Record<Tier, ReadonlyArray<Feature>> = {
  free: FREE_FEATURES,
  pro: PRO_FEATURES,
  studio: STUDIO_FEATURES,
};

/**
 * Max `num_videos` a single topic job may request, per tier. Mirrors
 * `backend/app/services/tier_service.py::TIER_CAPABILITIES["num_videos_cap"]`
 * — the backend enforces this with a 403 at job creation; this mirror is
 * for form UX (input max + helper copy) only.
 */
const NUM_VIDEOS_CAP_BY_TIER: Record<Tier, number> = {
  free: 100,
  pro: 250,
  studio: 500,
};

export function numVideosCapForTier(tier: Tier): number {
  return NUM_VIDEOS_CAP_BY_TIER[tier] ?? NUM_VIDEOS_CAP_BY_TIER.free;
}

export function featuresForTier(tier: Tier): ReadonlyArray<Feature> {
  return FEATURES_BY_TIER[tier] ?? FREE_FEATURES;
}

export function hasFeatureForTier(tier: Tier, feature: Feature): boolean {
  return FEATURES_BY_TIER[tier]?.includes(feature) ?? false;
}

/**
 * Returns the current user's tier + a `has(feature)` predicate. Defaults
 * to `free` when the `/auth/me` query hasn't resolved yet (or hasn't run)
 * so the UI never shows a feature the user shouldn't have.
 */
export function useTierCapabilities() {
  const { data, isLoading } = useMe();
  const tier: Tier = data?.tier ?? 'free';
  return {
    tier,
    isLoading,
    has: (feature: Feature) => hasFeatureForTier(tier, feature),
    features: featuresForTier(tier),
    numVideosCap: numVideosCapForTier(tier),
  };
}
