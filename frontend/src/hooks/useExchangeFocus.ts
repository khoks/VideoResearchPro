import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Land on one Q&A exchange (S-8.2.2): palette and search results link to
 * `…?exchange=<id>`, in-app references to `#exchange-<id>`. Once the list
 * has rendered (`ready`), scroll the card with id `exchange-<id>` into view,
 * move focus to it and outline it briefly, so the landing is visible and
 * screen-reader users arrive at the same place.
 */
export function useExchangeFocus(ready: boolean) {
  const [params] = useSearchParams();
  const fromQuery = params.get('exchange');

  useEffect(() => {
    if (!ready) return;
    const hash = window.location.hash;
    const id = fromQuery ?? (hash.startsWith('#exchange-') ? hash.slice('#exchange-'.length) : null);
    if (!id) return;
    const el = document.getElementById(`exchange-${id}`);
    if (!el) return;
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    el.scrollIntoView?.({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
    if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
    el.focus({ preventScroll: true });
    const previous = el.style.boxShadow;
    el.style.boxShadow = '0 0 0 2px var(--color-focus)';
    const t = window.setTimeout(() => {
      el.style.boxShadow = previous;
    }, 2500);
    return () => window.clearTimeout(t);
  }, [ready, fromQuery]);
}
