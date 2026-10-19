/**
 * The reading-room layout (ui-design §2.3): title block, a 75ch measure of
 * serif body text with a drop cap, a sticky outline on the right, and a
 * reading-progress pill. Reports (S-8.8.1), knowledge artifacts and books
 * (S-8.8.3) all render through this shell; only the body differs.
 *
 * The body's typography lives in `index.css` under `.reader-body`, because
 * the content is arbitrary sanitised HTML and inline styles cannot reach
 * into it. Everything the shell owns is inline-styled from the tokens.
 */
import { useRef, type ReactNode } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../../theme';
import { Outline } from './Outline';
import { ReadingProgress, useReadingProgress } from './ReadingProgress';
import { useActiveHeading } from './useActiveHeading';
import type { OutlineEntry } from './parseReport';

export interface ReaderShellProps {
  /** Small uppercase label above the title: "Research report", "Knowledge report"… */
  kicker?: string;
  title: string;
  /** Meta line under the title: date, counts. */
  meta?: ReactNode;
  /** Toolbar: back link, print… */
  actions?: ReactNode;
  /** Rendered between the header and the body (statistics tiles). */
  before?: ReactNode;
  outline: OutlineEntry[];
  /** The parsed body. */
  children: ReactNode;
}

export function ReaderShell({ kicker, title, meta, actions, before, outline, children }: ReaderShellProps) {
  const c = useColors();
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const activeId = useActiveHeading(bodyRef, outline);
  const progress = useReadingProgress();

  return (
    <article className="reader-grid">
      <div style={{ minWidth: 0 }}>
        <header style={{ maxWidth: measure.reading, marginBottom: space['6'] }}>
          {kicker && (
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
              {kicker}
            </p>
          )}
          <h1
            style={{
              margin: 0,
              fontFamily: fonts.display,
              fontSize: fontSize['2xl'],
              fontWeight: fontWeight.semibold,
              lineHeight: lineHeight.tight,
              color: c.textPrimary,
              textWrap: 'balance',
            }}
          >
            {title}
          </h1>
          {meta && (
            <p
              style={{
                margin: `${space['3']} 0 0`,
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                color: c.textSecondary,
                lineHeight: lineHeight.snug,
              }}
            >
              {meta}
            </p>
          )}
          {actions && (
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: space['2'],
                marginTop: space['4'],
              }}
            >
              {actions}
            </div>
          )}
        </header>
        {before}
        <div ref={bodyRef} className="reader-body">
          {children}
        </div>
      </div>
      <Outline entries={outline} activeId={activeId} progress={progress} />
      <ReadingProgress value={progress} />
    </article>
  );
}
