/**
 * Inline citation chip inside report prose (S-8.8.1, cards S-8.8.2).
 *
 * The chip keeps the writer's own text (usually the `mm:ss` stamp, which is
 * part of the sentence) and adds a footnote number that shows in print. A
 * chip with a link opens the source at the timestamp; one without (a
 * pre-S-1.14.9 report whose source the reader could not recover) is a
 * button, so keyboard users still reach it and its card.
 *
 * Hover and focus open the shared card through `CitationCardProvider`;
 * without a provider (tests, other surfaces) the chip renders plainly.
 */
import { useRef, type CSSProperties, type FocusEvent, type MouseEvent, type PointerEvent } from 'react';
import { useColors } from '../../hooks/useTheme';
import { openApiLink } from '../../services/apiFiles';
import { fonts, fontSize, radius, space } from '../../theme';
import { citedFileFailed } from '../citation/citedFile';
import { useCitationUi } from './CitationContext';
import type { ReportCitation } from './parseReport';

export function ReaderCitation({ citation }: { citation: ReportCitation }) {
  const c = useColors();
  const ui = useCitationUi();
  // Touch has no hover, so the first tap on a linked chip previews its card
  // and a second tap (or the card's own link) opens the source (S-8.12.1).
  // Recorded at pointerdown because the tap's focus event opens the card
  // before the click arrives.
  const touchPreview = useRef(false);
  // Whether the card was already open when the pointer went down; null for a
  // keyboard activation. A click focuses the chip first (which opens the
  // card), so "open at click time" cannot tell a first click from a second.
  const openAtPointerDown = useRef<boolean | null>(null);
  const resolved = ui?.index?.byIndex.get(citation.index) ?? null;
  const href = resolved?.resolvedHref ?? citation.href;
  const source = resolved?.source ?? null;
  const footnote = resolved?.footnote ?? citation.index;

  const base: CSSProperties = {
    display: 'inline-block',
    fontFamily: fonts.mono,
    fontSize: fontSize.xs,
    lineHeight: 1.6,
    padding: `0 ${space['2']}`,
    borderRadius: radius.pill,
    border: `1px solid ${c.border}`,
    whiteSpace: 'nowrap',
    verticalAlign: 'baseline',
    textDecoration: 'none',
  };

  const describe = source ? `${source.title}${source.channel_name ? `, ${source.channel_name}` : ''}` : null;
  const handlers = ui
    ? {
        onPointerDown: (e: PointerEvent<HTMLElement>) => {
          const open = ui.isOpen(citation.index);
          openAtPointerDown.current = open;
          touchPreview.current = e.pointerType === 'touch' && !open;
        },
        onMouseEnter: (e: MouseEvent<HTMLElement>) => ui.show(citation.index, e.currentTarget),
        onMouseLeave: () => ui.hide(),
        onFocus: (e: FocusEvent<HTMLElement>) => ui.show(citation.index, e.currentTarget, true),
        onBlur: () => ui.hide(true),
      }
    : {};
  const fn = (
    <sup className="reader-fn" aria-hidden="true">
      {footnote}
    </sup>
  );

  if (href) {
    return (
      <a
        className="reader-citation"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`${citation.label}${describe ? `, ${describe}` : ''}, opens in a new tab`}
        style={{ ...base, color: c.accent, background: c.accentSubtle }}
        {...handlers}
        onClick={(e) => {
          if (ui && touchPreview.current) {
            touchPreview.current = false;
            e.preventDefault();
            ui.show(citation.index, e.currentTarget, true);
            return;
          }
          // A source served by the API (an uploaded PDF) takes the bearer
          // header only; open it as a blob URL rather than a link that 401s.
          openApiLink(e, href, citedFileFailed);
        }}
        onAuxClick={(e) => openApiLink(e, href, citedFileFailed)}
      >
        {citation.label}
        {fn}
      </a>
    );
  }

  return (
    <button
      type="button"
      className="reader-citation reader-citation--unresolved"
      aria-label={`${citation.label}, ${describe ?? 'source not recorded in this report'}`}
      onClick={
        ui
          ? (e) => {
              const wasOpen = openAtPointerDown.current;
              openAtPointerDown.current = null;
              if (wasOpen === null) ui.toggle(citation.index, e.currentTarget);
              else if (wasOpen) ui.hide(true);
              else ui.show(citation.index, e.currentTarget, true);
            }
          : undefined
      }
      style={{ ...base, color: c.textMuted, background: c.surfaceAlt, cursor: ui ? 'pointer' : 'default' }}
      {...handlers}
    >
      {citation.label}
      {fn}
    </button>
  );
}
