/**
 * One hover card for every citation chip in a report (S-8.8.2).
 *
 * A large report carries hundreds of chips, so they do not each own a card.
 * The provider holds the resolved citation index and a single `CitationCard`;
 * chips call `show` / `hide`. The context value only changes when the index
 * does, so hovering never re-renders the chips — `aria-describedby` is set on
 * the active chip imperatively for the same reason.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { CitationCard, type CitationStill } from './CitationCard';
import type { CitationIndex, ResolvedCitation } from './citations';

const SHOW_DELAY_MS = 120;
const HIDE_DELAY_MS = 160;
export const CITATION_CARD_ID = 'reader-citation-card';

interface CitationUi {
  index: CitationIndex | null;
  /** `immediate` for keyboard focus and taps; hover waits a beat. */
  show: (citationIndex: number, anchor: HTMLElement, immediate?: boolean) => void;
  hide: (immediate?: boolean) => void;
  toggle: (citationIndex: number, anchor: HTMLElement) => void;
  /** Whether this chip's card is the open one (read at event time; no re-render). */
  isOpen: (citationIndex: number) => boolean;
}

const Ctx = createContext<CitationUi | null>(null);

export function useCitationUi(): CitationUi | null {
  return useContext(Ctx);
}

export interface CitationCardProviderProps {
  index: CitationIndex | null;
  /**
   * R1 hook (T-8.8.2.3): once S-1.18.2 serves `visual_frames`, return the
   * still nearest the cited timestamp and the card shows it. Nothing supplies
   * one yet.
   */
  resolveStill?: (citation: ResolvedCitation) => CitationStill | null;
  children: ReactNode;
}

export function CitationCardProvider({ index, resolveStill, children }: CitationCardProviderProps) {
  const [active, setActive] = useState<{ n: number; anchor: HTMLElement } | null>(null);
  // Bumped on scroll and resize so the card follows its chip.
  const [layoutTick, setLayoutTick] = useState(0);
  const showTimer = useRef<number | undefined>(undefined);
  const hideTimer = useRef<number | undefined>(undefined);
  const activeRef = useRef(active);
  activeRef.current = active;

  const clearTimers = () => {
    window.clearTimeout(showTimer.current);
    window.clearTimeout(hideTimer.current);
  };

  const hide = useCallback((immediate = false) => {
    window.clearTimeout(showTimer.current);
    window.clearTimeout(hideTimer.current);
    const run = () => {
      activeRef.current?.anchor.removeAttribute('aria-describedby');
      setActive(null);
    };
    if (immediate) run();
    else hideTimer.current = window.setTimeout(run, HIDE_DELAY_MS);
  }, []);

  const show = useCallback((n: number, anchor: HTMLElement, immediate = false) => {
    clearTimers();
    const run = () => {
      const prev = activeRef.current;
      if (prev && prev.anchor !== anchor) prev.anchor.removeAttribute('aria-describedby');
      anchor.setAttribute('aria-describedby', CITATION_CARD_ID);
      setActive({ n, anchor });
    };
    if (immediate || activeRef.current) run();
    else showTimer.current = window.setTimeout(run, SHOW_DELAY_MS);
  }, []);

  const toggle = useCallback(
    (n: number, anchor: HTMLElement) => {
      if (activeRef.current?.n === n) hide(true);
      else show(n, anchor, true);
    },
    [hide, show],
  );

  const isOpen = useCallback((n: number) => activeRef.current?.n === n, []);

  // Escape closes. Scrolling moves the card with its chip and closes it only
  // once the chip has left the viewport. (Closing on any scroll broke keyboard
  // use: tabbing to a chip scrolls it into view, which fired the close.)
  useEffect(() => {
    if (!active) return;
    let frame = 0;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') hide(true);
    };
    const follow = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const r = active.anchor.getBoundingClientRect();
        if (r.bottom < 0 || r.top > window.innerHeight || !active.anchor.isConnected) hide(true);
        else setLayoutTick((t) => t + 1);
      });
    };
    // A tap or click outside both the card and its chip closes it (touch has
    // no mouseleave).
    const onPointerDown = (e: PointerEvent) => {
      const t = e.target as Node | null;
      const card = document.getElementById(CITATION_CARD_ID);
      if (t && (active.anchor.contains(t) || card?.contains(t))) return;
      hide(true);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('scroll', follow, { passive: true });
    window.addEventListener('resize', follow);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('scroll', follow);
      window.removeEventListener('resize', follow);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [active, hide]);

  useEffect(() => () => clearTimers(), []);

  const value = useMemo<CitationUi>(
    () => ({ index, show, hide, toggle, isOpen }),
    [index, show, hide, toggle, isOpen],
  );
  const citation = active && index ? (index.byIndex.get(active.n) ?? null) : null;

  return (
    <Ctx.Provider value={value}>
      {children}
      <CitationCard
        id={CITATION_CARD_ID}
        citation={citation}
        anchor={active?.anchor ?? null}
        layoutTick={layoutTick}
        still={citation && resolveStill ? resolveStill(citation) : null}
        onPointerEnter={() => window.clearTimeout(hideTimer.current)}
        onPointerLeave={() => hide()}
      />
    </Ctx.Provider>
  );
}
