import { useSystemStatusStore } from '../stores/systemStatusStore';

/**
 * An install-level switch from `/health` `capabilities`. `fallback` is used
 * until the first poll answers (null capabilities) or when the key is absent.
 */
export function useCapability(name: string, fallback = false): boolean {
  const capabilities = useSystemStatusStore((s) => s.capabilities);
  const value = capabilities?.[name];
  return typeof value === 'boolean' ? value : fallback;
}
