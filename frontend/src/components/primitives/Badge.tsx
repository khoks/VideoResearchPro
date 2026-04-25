import type { CSSProperties, ReactNode } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';

export type BadgeTone = 'neutral' | 'success' | 'warn' | 'error' | 'info' | 'accent';
export type BadgeSize = 'sm' | 'md';

export interface BadgeProps {
  tone?: BadgeTone;
  size?: BadgeSize;
  children: ReactNode;
  style?: CSSProperties;
}

export function Badge({ tone = 'neutral', size = 'md', children, style }: BadgeProps) {
  const c = useColors();

  const toneStyles: Record<BadgeTone, CSSProperties> = {
    neutral: { background: c.surfaceAlt, color: c.textSecondary, borderColor: c.border },
    success: { background: c.successSubtle, color: c.success, borderColor: c.success },
    warn:    { background: c.warnSubtle,    color: c.warn,    borderColor: c.warn },
    error:   { background: c.errorSubtle,   color: c.error,   borderColor: c.error },
    info:    { background: c.infoSubtle,    color: c.info,    borderColor: c.info },
    accent:  { background: c.accentSubtle,  color: c.accent,  borderColor: c.accent },
  };

  const sizeStyles: Record<BadgeSize, CSSProperties> = {
    sm: { padding: `2px ${space['2']}`, fontSize: fontSize.xs, minHeight: 18 },
    md: { padding: `${space['1']} ${space['3']}`, fontSize: fontSize.xs, minHeight: 22 },
  };

  const base: CSSProperties = {
    fontFamily: fonts.ui,
    fontWeight: fontWeight.medium,
    borderRadius: radius.pill,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    border: '1px solid',
    lineHeight: 1,
    whiteSpace: 'nowrap',
    letterSpacing: '0.02em',
  };

  return (
    <span style={{ ...base, ...sizeStyles[size], ...toneStyles[tone], ...style }}>{children}</span>
  );
}

/**
 * Job status → badge tone mapping. Keep in sync with backend job states.
 */
const JOB_STATUS_TONE: Record<string, BadgeTone> = {
  pending: 'neutral',
  searching: 'info',
  awaiting_approval: 'warn',
  extracting: 'info',
  building_rag: 'info',
  generating_report: 'info',
  completed: 'success',
  cancelled: 'neutral',
  failed: 'error',
};

const JOB_STATUS_LABEL: Record<string, string> = {
  pending: 'Pending',
  searching: 'Searching',
  awaiting_approval: 'Awaiting approval',
  extracting: 'Extracting',
  building_rag: 'Building RAG',
  generating_report: 'Generating report',
  completed: 'Completed',
  cancelled: 'Cancelled',
  failed: 'Failed',
};

export function StatusPill({ status, size = 'md' }: { status: string; size?: BadgeSize }) {
  const tone = JOB_STATUS_TONE[status] ?? 'neutral';
  const label = JOB_STATUS_LABEL[status] ?? status.replace(/_/g, ' ');
  return (
    <Badge tone={tone} size={size}>
      {label}
    </Badge>
  );
}
