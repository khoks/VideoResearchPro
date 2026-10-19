import { useEffect, useState, type RefObject } from 'react';
import type { OutlineEntry } from './parseReport';

/**
 * Which outline entry the reader is "in": the last heading whose top has
 * passed the upper quarter of the viewport. One IntersectionObserver over the
 * body's headings fires only when a heading crosses that band, and each firing
 * re-reads a few dozen rects — cheap, and no scroll listener.
 */
export function useActiveHeading(
  containerRef: RefObject<HTMLElement | null>,
  entries: OutlineEntry[],
): string | null {
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || entries.length === 0 || typeof IntersectionObserver === 'undefined') {
      setActiveId(entries[0]?.id ?? null);
      return;
    }
    const headings = Array.from(container.querySelectorAll<HTMLElement>('h2[id], h3[id]'));
    if (headings.length === 0) {
      setActiveId(null);
      return;
    }

    const compute = () => {
      const band = window.innerHeight * 0.25;
      let current: HTMLElement | null = null;
      for (const h of headings) {
        if (h.getBoundingClientRect().top <= band) current = h;
        else break;
      }
      setActiveId((current ?? headings[0]).id);
    };

    const observer = new IntersectionObserver(compute, {
      rootMargin: '0px 0px -75% 0px',
      threshold: [0, 1],
    });
    headings.forEach((h) => observer.observe(h));
    compute();
    return () => observer.disconnect();
  }, [containerRef, entries]);

  return activeId;
}
