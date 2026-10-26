/**
 * A stand-in for the tab `openApiFile` opens (T-8.8.1.5): it calls
 * `window.open('', '_blank')` inside the click, cuts the opener, and sets the
 * blob URL on the tab's location once the bytes arrive. jsdom cannot open
 * tabs, so `window.open` hands back one of these and the test reads what
 * happened to it.
 */
import { vi } from 'vitest';

export interface FakeTab {
  opener: unknown;
  closed: boolean;
  location: { href: string };
  document: Document;
  close(): void;
}

export function stubNewTabs() {
  const tabs: FakeTab[] = [];
  const open = vi.fn((): FakeTab | null => {
    const tab: FakeTab = {
      opener: window,
      closed: false,
      location: { href: 'about:blank' },
      document: document.implementation.createHTMLDocument(''),
      close() {
        tab.closed = true;
      },
    };
    tabs.push(tab);
    return tab;
  });
  window.open = open as unknown as typeof window.open;
  return { open, tabs };
}
