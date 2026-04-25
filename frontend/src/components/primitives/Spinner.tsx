import type { CSSProperties } from 'react';
import { useColors } from '../../hooks/useTheme';
import { radius, motion } from '../../theme';

export interface SpinnerProps {
  size?: number;
  /** Override the circle color. Defaults to `accent`. */
  color?: string;
  label?: string;
  style?: CSSProperties;
}

export function Spinner({ size = 16, color, label = 'Loading', style }: SpinnerProps) {
  const c = useColors();
  const stroke = color ?? c.accent;
  return (
    <span
      role="status"
      aria-label={label}
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        borderRadius: '50%',
        border: `2px solid ${stroke}`,
        borderTopColor: 'transparent',
        animation: 'spin 700ms linear infinite',
        ...style,
      }}
    />
  );
}

export interface SkeletonProps {
  variant?: 'text' | 'paragraph' | 'card' | 'row';
  width?: number | string;
  height?: number | string;
  style?: CSSProperties;
}

export function Skeleton({ variant = 'text', width, height, style }: SkeletonProps) {
  const c = useColors();

  const dims: Record<NonNullable<SkeletonProps['variant']>, CSSProperties> = {
    text:      { width: width ?? '60%',  height: height ?? 14 },
    paragraph: { width: width ?? '100%', height: height ?? 14 },
    card:      { width: width ?? '100%', height: height ?? 120 },
    row:       { width: width ?? '100%', height: height ?? 48 },
  };

  const base: CSSProperties = {
    display: 'block',
    background: `linear-gradient(90deg, ${c.surfaceAlt} 0%, ${c.border} 50%, ${c.surfaceAlt} 100%)`,
    backgroundSize: '800px 100%',
    borderRadius: radius.sm,
    animation: `pratidhvani-shimmer 1.4s ${motion.easing.standard} infinite`,
  };

  if (variant === 'paragraph') {
    return (
      <div aria-hidden style={{ display: 'flex', flexDirection: 'column', gap: 8, ...style }}>
        <span style={{ ...base, ...dims.paragraph, width: '95%' }} />
        <span style={{ ...base, ...dims.paragraph, width: '88%' }} />
        <span style={{ ...base, ...dims.paragraph, width: '72%' }} />
      </div>
    );
  }

  return <span aria-hidden style={{ ...base, ...dims[variant], ...style }} />;
}
