import { useSystemStatusStore } from '../stores/systemStatusStore';

// Returns false only when the backend explicitly reports the feature as
// unavailable. When status is "unknown" (initial load before first poll) we
// fail safe and allow the feature — users shouldn't be locked out while we
// wait for the first health response.
export function useFeatureAvailable(featureName: string): boolean {
  const llmStatus = useSystemStatusStore((s) => s.llmStatus);
  const unavailableFeatures = useSystemStatusStore((s) => s.unavailableFeatures);

  if (unavailableFeatures.includes(featureName)) return false;
  return llmStatus === 'ok' || llmStatus === 'unknown';
}
