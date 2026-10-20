import { useSystemStatusStore } from '../stores/systemStatusStore';

// False when the backend reports THIS feature unavailable, or when every
// model is down. "degraded" means some other feature failed its probe; it
// must not grey out this one. Before S-1.18.2 any degraded status disabled
// every feature, so a vision-only outage would have switched off Q&A and
// reports too, against llm_smoke's own intent ("only the affected surface
// degrades"). When status is "unknown" (before the first poll) we fail safe
// and allow the feature.
export function useFeatureAvailable(featureName: string): boolean {
  const llmStatus = useSystemStatusStore((s) => s.llmStatus);
  const unavailableFeatures = useSystemStatusStore((s) => s.unavailableFeatures);

  if (unavailableFeatures.includes(featureName)) return false;
  return llmStatus !== 'down';
}

