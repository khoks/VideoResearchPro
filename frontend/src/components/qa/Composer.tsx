/**
 * The Q&A composer, docked at the bottom on phones (S-8.12.1, ui-design
 * §2.4: "Q&A textarea: docked at bottom; chat-like").
 *
 * Wrap the page's Q&A card body in `<QADock>`, the question form in
 * `<DockedComposer>` and the exchange list in `<QAThread>`. On wide screens
 * nothing changes. Under 640 px (CSS in index.css) the dock becomes a flex
 * column, the thread — oldest first, as the API returns it — comes before
 * the composer, and the composer sticks to the bottom of the viewport while
 * the card is on screen, like a chat.
 *
 * The on-screen keyboard does not shrink the layout viewport on iOS Safari
 * or (by default) Chrome on Android, so a bottom-stuck element ends up
 * behind it. `useKeyboardInset` reads the VisualViewport API on `resize` and
 * `scroll`, rAF-throttled, and the composer lifts itself by that much.
 */
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';

const DOCK_QUERY = '(max-width: 640px)';

interface ViewportLike {
  height: number;
  offsetTop: number;
  scale: number;
}

/**
 * How much of the layout viewport's bottom the visual viewport no longer
 * shows — the keyboard, near enough. Zero when pinch-zoomed: the visual
 * viewport is then smaller for a reason that is not a keyboard.
 */
export function keyboardInset(layoutHeight: number, vv: ViewportLike): number {
  if (Math.abs(vv.scale - 1) > 0.01) return 0;
  return Math.max(0, Math.round(layoutHeight - vv.height - vv.offsetTop));
}

export function useKeyboardInset(): number {
  const [inset, setInset] = useState(0);
  useEffect(() => {
    const vv = typeof window !== 'undefined' ? window.visualViewport : null;
    if (!vv) return;
    const mq = window.matchMedia?.(DOCK_QUERY);
    let frame = 0;
    const update = () => {
      frame = 0;
      setInset(mq && !mq.matches ? 0 : keyboardInset(window.innerHeight, vv));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    vv.addEventListener('resize', schedule);
    vv.addEventListener('scroll', schedule);
    mq?.addEventListener?.('change', schedule);
    update();
    return () => {
      vv.removeEventListener('resize', schedule);
      vv.removeEventListener('scroll', schedule);
      mq?.removeEventListener?.('change', schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  return inset;
}

export function QADock({ children }: { children: ReactNode }) {
  return <div className="qa-dock">{children}</div>;
}

export function QAThread({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div className="qa-thread" style={style}>
      {children}
    </div>
  );
}

export function DockedComposer({ children }: { children: ReactNode }) {
  const inset = useKeyboardInset();
  return (
    <div className="qa-composer" style={{ '--kb-inset': `${inset}px` } as CSSProperties}>
      {children}
    </div>
  );
}
