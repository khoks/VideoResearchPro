/**
 * The citation hover / focus card (S-8.8.2, ui-design §2.3).
 *
 * Uses the Popover API (Baseline 2025) so the card sits in the top layer
 * above every stacking context; positioned from the chip's bounding rect
 * because CSS anchor positioning is still partial. Where `showPopover` is
 * missing (older engines, jsdom) it falls back to a fixed element at the
 * tooltip z-index — same look, same placement.
 *
 * Polymorphic by the source's `source_type` through `describeSource`.
 */
import { useLayoutEffect, useRef } from 'react';
import { useColors, useShadows } from '../../hooks/useTheme';
import { openApiLink } from '../../services/apiFiles';
import { formatDuration } from '../../utils/formatters';
import { citedFileFailed } from '../citation/citedFile';
import { fonts, fontSize, fontWeight, lineHeight, radius, space, z } from '../../theme';
import type { ResolvedCitation } from './citations';
import { placeCard } from './placeCard';
import { describeSource } from './sourceLabels';

export interface CitationStill {
  src: string;
  alt: string;
}

interface CitationCardProps {
  id: string;
  citation: ResolvedCitation | null;
  anchor: HTMLElement | null;
  /** Changes whenever the page scrolls or resizes under an open card. */
  layoutTick?: number;
  still: CitationStill | null;
  onPointerEnter: () => void;
  onPointerLeave: () => void;
}

const CARD_WIDTH = 340;

function supportsPopover(): boolean {
  return typeof HTMLElement !== 'undefined' && 'showPopover' in HTMLElement.prototype;
}

export function CitationCard({
  id,
  citation,
  anchor,
  layoutTick,
  still,
  onPointerEnter,
  onPointerLeave,
}: CitationCardProps) {
  const c = useColors();
  const s = useShadows();
  const ref = useRef<HTMLDivElement | null>(null);
  const popover = supportsPopover();

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const open = popover && el.matches(':popover-open');
    if (!citation || !anchor) {
      if (open) el.hidePopover();
      return;
    }
    if (popover && !open) el.showPopover();
    const a = anchor.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    const p = placeCard(
      { top: a.top, left: a.left, width: a.width, height: a.height },
      { width: box.width || CARD_WIDTH, height: box.height },
      { width: window.innerWidth, height: window.innerHeight },
    );
    el.style.top = `${p.top}px`;
    el.style.left = `${p.left}px`;
    el.dataset.side = p.side;
  }, [citation, anchor, popover, layoutTick]);

  const desc = citation?.source ? describeSource(citation.source) : null;
  const at = citation?.seconds != null ? formatDuration(citation.seconds) : null;
  const showAt = at != null && (desc ? desc.timed : true);

  return (
    <div
      ref={ref}
      id={id}
      role="tooltip"
      className="reader-citation-card"
      popover={popover ? 'manual' : undefined}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      style={{
        position: 'fixed',
        inset: 'auto',
        margin: 0,
        display: popover ? undefined : citation ? 'block' : 'none',
        zIndex: z.tooltip,
        width: `min(${CARD_WIDTH}px, calc(100vw - 16px))`,
        padding: space['4'],
        background: c.surface,
        color: c.textPrimary,
        border: `1px solid ${c.border}`,
        borderRadius: radius.md,
        boxShadow: s.floating,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        lineHeight: lineHeight.snug,
        overflow: 'hidden',
      }}
    >
      {citation && (
        <>
          {still && (
            <img
              src={still.src}
              alt={still.alt}
              style={{
                display: 'block',
                width: `calc(100% + 2 * ${space['4']})`,
                margin: `-${space['4']} -${space['4']} ${space['3']}`,
                aspectRatio: '16 / 9',
                objectFit: 'cover',
                background: c.surfaceAlt,
              }}
            />
          )}
          <p
            style={{
              margin: 0,
              fontSize: fontSize.xs,
              fontWeight: fontWeight.semibold,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: c.textMuted,
            }}
          >
            {desc?.kind ?? 'Source'} · note {citation.footnote}
          </p>
          {citation.source ? (
            <>
              <p
                style={{
                  margin: `${space['1']} 0 0`,
                  fontFamily: fonts.display,
                  fontSize: fontSize.md,
                  fontWeight: fontWeight.semibold,
                  lineHeight: lineHeight.tight,
                  color: c.textPrimary,
                }}
              >
                {citation.source.title}
              </p>
              {desc && desc.meta.length > 0 && (
                <p style={{ margin: `${space['1']} 0 0`, color: c.textSecondary }}>{desc.meta.join(' · ')}</p>
              )}
            </>
          ) : (
            <p style={{ margin: `${space['1']} 0 0`, color: c.textSecondary }}>
              This report did not record which source the timestamp belongs to, and its text names none of
              this run's sources.
            </p>
          )}
          {(showAt || citation.resolvedHref) && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: space['3'],
                marginTop: space['3'],
                paddingTop: space['3'],
                borderTop: `1px solid ${c.border}`,
              }}
            >
              {showAt ? (
                <span style={{ fontFamily: fonts.mono, fontSize: fontSize.xs, color: c.textSecondary }}>
                  at {at}
                </span>
              ) : (
                <span />
              )}
              {citation.resolvedHref && (
                <a
                  href={citation.resolvedHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => openApiLink(e, citation.resolvedHref, citedFileFailed)}
                  onAuxClick={(e) => openApiLink(e, citation.resolvedHref, citedFileFailed)}
                  tabIndex={-1}
                  style={{ color: c.accent, fontWeight: fontWeight.medium }}
                >
                  {showAt ? `Open at ${at}` : 'Open source'} ↗
                </a>
              )}
            </div>
          )}
          {(citation.resolvedBy === 'title' || citation.resolvedBy === 'channel') && (
            <p style={{ margin: `${space['2']} 0 0`, fontSize: fontSize.xs, color: c.textMuted }}>
              Matched by the {citation.resolvedBy} named beside the timestamp; this report predates stored links.
            </p>
          )}
        </>
      )}
    </div>
  );
}
