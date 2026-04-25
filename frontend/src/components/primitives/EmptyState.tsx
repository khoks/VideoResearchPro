import type { CSSProperties, ReactNode } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';

export interface EmptyStateProps {
  /** Short noun phrase, displayed in the display serif at fontSize.xl. */
  title: ReactNode;
  /** 1-2 sentences. Editorial voice per branding.md — never 'No data.'. */
  description?: ReactNode;
  /** Optional call-to-action — typically a <Button>. */
  action?: ReactNode;
  /** Optional SVG / icon shown above the title. */
  icon?: ReactNode;
  /** Sets the outer padding. Defaults to `7` (40 px). `sm` = `5` for in-card empties. */
  size?: 'sm' | 'md';
  style?: CSSProperties;
}

export function EmptyState({ title, description, action, icon, size = 'md', style }: EmptyStateProps) {
  const c = useColors();
  const pad = size === 'sm' ? space['5'] : space['7'];

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        padding: `${pad} ${space['5']}`,
        background: c.surface,
        border: `1px dashed ${c.border}`,
        borderRadius: radius.md,
        gap: space['3'],
        ...style,
      }}
    >
      {icon && (
        <div style={{ color: c.textMuted, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {icon}
        </div>
      )}
      <h3
        style={{
          fontFamily: fonts.display,
          fontSize: fontSize.xl,
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
          margin: 0,
          lineHeight: 1.25,
        }}
      >
        {title}
      </h3>
      {description && (
        <p
          style={{
            fontFamily: fonts.body,
            fontSize: fontSize.base,
            color: c.textSecondary,
            maxWidth: '48ch',
            lineHeight: 1.55,
            margin: 0,
          }}
        >
          {description}
        </p>
      )}
      {action && <div style={{ marginTop: space['2'] }}>{action}</div>}
    </div>
  );
}
