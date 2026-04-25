import { Spinner } from '../primitives';

/**
 * Thin wrapper around the token-driven `Spinner` primitive. Preserved as a
 * stable import path while pages migrate off the legacy name. New call sites
 * should import `Spinner` directly from `../primitives`.
 */
export function LoadingSpinner({ size = 24 }: { size?: number }) {
  return <Spinner size={size} />;
}
