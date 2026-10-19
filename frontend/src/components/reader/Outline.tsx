import { useState, type MouseEvent } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import type { OutlineEntry } from './parseReport';

interface OutlineProps {
  entries: OutlineEntry[];
  activeId: string | null;
  /** 0..1, announced as "Reading n%". */
  progress: number;
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Sticky section outline built from the report's own headings (ui-design
 * §2.3). Plain hash links keep it usable without JS; the click handler only
 * adds the smooth scroll (unless the user asked for reduced motion) and moves
 * focus to the heading so keyboard users land where they expect.
 */
export function Outline({ entries, activeId, progress }: OutlineProps) {
  const c = useColors();
  if (entries.length === 0) return null;

  const onJump = (e: MouseEvent<HTMLAnchorElement>, id: string) => {
    const target = document.getElementById(id);
    if (!target) return; // let the browser handle the hash
    e.preventDefault();
    target.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
    target.focus({ preventScroll: true });
    window.history.replaceState(null, '', `#${id}`);
  };

  return (
    <nav aria-label="Outline" className="reader-outline">
      <p
        style={{
          margin: `0 0 ${space['2']}`,
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          fontWeight: fontWeight.semibold,
          color: c.textMuted,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
        }}
      >
        Outline
      </p>
      <ol style={{ listStyle: 'none', margin: 0, padding: 0, borderLeft: `1px solid ${c.border}` }}>
        {entries.map((entry) => (
          <li key={entry.id}>
            <OutlineLink entry={entry} active={entry.id === activeId} onJump={onJump} />
          </li>
        ))}
      </ol>
      <p
        style={{
          margin: `${space['3']} 0 0`,
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          color: c.textMuted,
        }}
      >
        Reading {Math.round(progress * 100)}%
      </p>
    </nav>
  );
}

function OutlineLink({
  entry,
  active,
  onJump,
}: {
  entry: OutlineEntry;
  active: boolean;
  onJump: (e: MouseEvent<HTMLAnchorElement>, id: string) => void;
}) {
  const c = useColors();
  const [hovered, setHovered] = useState(false);
  return (
    <a
      href={`#${entry.id}`}
      aria-current={active ? 'true' : undefined}
      onClick={(e) => onJump(e, entry.id)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'block',
        padding: `${space['1']} ${space['3']}`,
        paddingLeft: entry.level === 3 ? space['6'] : space['3'],
        marginLeft: -1,
        borderLeft: `2px solid ${active ? c.accent : 'transparent'}`,
        borderRadius: `0 ${radius.sm} ${radius.sm} 0`,
        background: hovered && !active ? c.surfaceAlt : 'transparent',
        color: active ? c.accent : c.textSecondary,
        fontFamily: fonts.ui,
        fontSize: entry.level === 3 ? fontSize.xs : fontSize.sm,
        fontWeight: active ? fontWeight.semibold : fontWeight.regular,
        lineHeight: lineHeight.snug,
        textDecoration: 'none',
      }}
    >
      {entry.text}
    </a>
  );
}
