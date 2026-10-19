import { useEffect, useState } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space, z } from '../../theme';

/** 0..1 of the document scrolled, rAF-throttled. */
export function useReadingProgress(): number {
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const el = document.documentElement;
      const max = el.scrollHeight - el.clientHeight;
      setProgress(max > 0 ? Math.min(1, Math.max(0, el.scrollTop / max)) : 1);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    return () => {
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  return progress;
}

/**
 * Floating "Reading · 32%" pill at the bottom right (ui-design §2.3).
 * Decorative: the same figure is read out in the outline for assistive tech.
 */
export function ReadingProgress({ value }: { value: number }) {
  const c = useColors();
  const pct = Math.round(value * 100);
  return (
    <div
      className="reader-progress"
      aria-hidden="true"
      style={{
        position: 'fixed',
        right: space['4'],
        bottom: space['4'],
        zIndex: z.sticky,
        display: 'flex',
        alignItems: 'center',
        gap: space['2'],
        padding: `${space['1']} ${space['3']}`,
        background: c.surface,
        border: `1px solid ${c.border}`,
        borderRadius: radius.pill,
        boxShadow: 'var(--shadow-card)',
        fontFamily: fonts.ui,
        fontSize: fontSize.xs,
        fontWeight: fontWeight.medium,
        color: c.textSecondary,
        pointerEvents: 'none',
      }}
    >
      <span
        style={{
          width: 64,
          height: 3,
          background: c.surfaceAlt,
          borderRadius: radius.pill,
          overflow: 'hidden',
        }}
      >
        <span
          style={{
            display: 'block',
            width: `${pct}%`,
            height: '100%',
            background: c.accent,
          }}
        />
      </span>
      <span>Reading · {pct}%</span>
    </div>
  );
}
