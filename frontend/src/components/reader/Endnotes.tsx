/**
 * Numbered list of every place the report cites (S-8.8.2).
 *
 * The print stylesheet turns chips into superscript numbers that point here,
 * and screen-reader users get the whole bibliography in one list. Collapsed
 * on screen (a long report cites well over a hundred places); forced open
 * for printing via `beforeprint`, because a closed `<details>` prints closed.
 */
import { useEffect, useState } from 'react';
import { useColors } from '../../hooks/useTheme';
import { openApiLink } from '../../services/apiFiles';
import { formatDuration } from '../../utils/formatters';
import { citedFileFailed } from '../citation/citedFile';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../../theme';
import type { Endnote } from './citations';
import { describeSource } from './sourceLabels';

export function Endnotes({ endnotes }: { endnotes: Endnote[] }) {
  const c = useColors();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let wasOpen = false;
    const before = () => {
      setOpen((o) => {
        wasOpen = o;
        return true;
      });
    };
    const after = () => setOpen(wasOpen);
    window.addEventListener('beforeprint', before);
    window.addEventListener('afterprint', after);
    return () => {
      window.removeEventListener('beforeprint', before);
      window.removeEventListener('afterprint', after);
    };
  }, []);

  if (endnotes.length === 0) return null;

  return (
    <section
      className="reader-endnotes"
      aria-labelledby="reader-endnotes-title"
      style={{
        maxWidth: measure.reading,
        marginTop: space['8'],
        paddingTop: space['5'],
        borderTop: `1px solid ${c.border}`,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        lineHeight: lineHeight.snug,
        color: c.textSecondary,
      }}
    >
      <details open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
        <summary
          style={{
            cursor: 'pointer',
            fontFamily: fonts.display,
            fontSize: fontSize.lg,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            padding: `${space['2']} 0`,
          }}
        >
          <span id="reader-endnotes-title">Sources cited</span>{' '}
          <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted, fontWeight: fontWeight.regular }}>
            · {endnotes.length} {endnotes.length === 1 ? 'note' : 'notes'}
          </span>
        </summary>
        <ol style={{ margin: `${space['3']} 0 0`, paddingLeft: space['6'] }}>
          {endnotes.map((n) => {
            const desc = n.source ? describeSource(n.source) : null;
            const at = n.seconds != null && (desc ? desc.timed : true) ? formatDuration(n.seconds) : null;
            const title = n.source?.title ?? `Timestamp ${n.label} (source not recorded in this report)`;
            return (
              <li key={n.footnote} id={`reader-fn-${n.footnote}`} value={n.footnote} style={{ marginBottom: space['2'] }}>
                {n.href ? (
                  <a
                    href={n.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => openApiLink(e, n.href, citedFileFailed)}
                    onAuxClick={(e) => openApiLink(e, n.href, citedFileFailed)}
                    style={{ color: c.accent }}
                  >
                    {title}
                  </a>
                ) : (
                  <span style={{ color: c.textPrimary }}>{title}</span>
                )}
                {desc && desc.meta.length > 0 && <span> — {desc.meta[0]}</span>}
                {at && <span style={{ fontFamily: fonts.mono, fontSize: fontSize.xs }}> · at {at}</span>}
                {n.count > 1 && <span style={{ color: c.textMuted }}> · cited {n.count}×</span>}
                {n.href && <span className="reader-endnote-url"> {n.href}</span>}
              </li>
            );
          })}
        </ol>
      </details>
    </section>
  );
}
