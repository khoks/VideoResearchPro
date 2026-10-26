import { useEffect, useState } from 'react';

/**
 * A blob: URL for `blob` that lives as long as the caller shows it: created
 * after render, revoked when the blob changes or the component unmounts
 * (StrictMode's extra mount included, which is why it is not a `useMemo`:
 * the strict cleanup would revoke a URL the second mount still uses).
 * Returns null until the URL exists.
 */
export function useObjectUrl(blob: Blob | null | undefined): string | null {
  const [entry, setEntry] = useState<{ blob: Blob; url: string } | null>(null);
  useEffect(() => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    // Syncing with the browser's blob URL store, an external system.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEntry({ blob, url });
    return () => URL.revokeObjectURL(url);
  }, [blob]);
  // Never hand out a URL made for an earlier blob (already revoked).
  return entry && entry.blob === blob ? entry.url : null;
}
