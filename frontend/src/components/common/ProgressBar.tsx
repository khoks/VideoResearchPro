import { useColors } from '../../hooks/useTheme';
import { radius } from '../../theme';

type ProgressTone = 'info' | 'accent' | 'warn' | 'success' | 'error' | 'neutral';

interface ProgressBarProps {
  value: number;
  /** Preferred: a semantic tone resolved against the theme. */
  tone?: ProgressTone;
  /** Escape hatch — explicit color override. Used by legacy `statusColor` callers. */
  color?: string;
}

export function ProgressBar({ value, tone = 'accent', color }: ProgressBarProps) {
  const c = useColors();
  const resolved =
    color ??
    (tone === 'info'    ? c.info
    : tone === 'accent'  ? c.accent
    : tone === 'warn'    ? c.warn
    : tone === 'success' ? c.success
    : tone === 'error'   ? c.error
    : c.textMuted);

  return (
    <div
      style={{
        background: c.surfaceAlt,
        borderRadius: radius.pill,
        height: 6,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          width: `${Math.min(100, Math.max(0, value))}%`,
          height: '100%',
          background: resolved,
          borderRadius: radius.pill,
          transition: 'width 500ms ease',
        }}
      />
    </div>
  );
}
