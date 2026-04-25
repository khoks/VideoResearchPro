import { StatusPill, type BadgeSize } from '../primitives';

/**
 * Thin wrapper around the token-driven `StatusPill` primitive. Preserved as a
 * stable import path while pages migrate off the legacy name. New call sites
 * should import `StatusPill` directly from `../primitives`.
 */
export function StatusBadge({ status, size = 'sm' }: { status: string; size?: BadgeSize }) {
  return <StatusPill status={status} size={size} />;
}
