import type { CSSProperties, ReactNode } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, space } from '../../theme';

export interface TabsProps {
  /** What the tabs choose between, for a screen reader. */
  label: string;
  children: ReactNode;
  style?: CSSProperties;
}

/** A row of underlined tabs. The active one is the parent's state, as is its panel. */
export function Tabs({ label, children, style }: TabsProps) {
  const c = useColors();
  return (
    <div
      role="tablist"
      aria-label={label}
      style={{
        display: 'flex',
        gap: space['1'],
        marginBottom: space['4'],
        borderBottom: `1px solid ${c.border}`,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export interface TabProps {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  style?: CSSProperties;
}

export function Tab({ active, onClick, children, style }: TabProps) {
  const c = useColors();
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      style={{
        background: 'transparent',
        color: active ? c.accent : c.textSecondary,
        border: 'none',
        borderBottom: `2px solid ${active ? c.accent : 'transparent'}`,
        padding: `${space['2']} ${space['4']}`,
        marginBottom: -1,
        cursor: 'pointer',
        fontFamily: fonts.ui,
        fontWeight: active ? fontWeight.semibold : fontWeight.medium,
        fontSize: fontSize.sm,
        letterSpacing: '0.02em',
        ...style,
      }}
    >
      {children}
    </button>
  );
}
