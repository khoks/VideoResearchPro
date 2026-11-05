import type { CSSProperties, KeyboardEvent, ReactNode } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, space } from '../../theme';

export interface TabsProps {
  /** What the tabs choose between, for a screen reader. */
  label: string;
  children: ReactNode;
  style?: CSSProperties;
}

/**
 * The ARIA tabs keyboard (T-2.2.5): the row is one stop for the Tab key, on the
 * active tab, and the arrows, Home and End move along it, wrapping. A tab opens
 * as it gets focus, through its own `onClick`: every panel here swaps in place
 * and spends nothing, which is when the pattern recommends that. With a modifier
 * held the key is the browser's: Alt and Left is Back.
 */
function moveAlongTabs(e: KeyboardEvent<HTMLDivElement>) {
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
  const tabs = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]'));
  const at = tabs.indexOf(e.target as HTMLElement);
  if (at < 0) return;
  const target: Record<string, number> = {
    ArrowRight: (at + 1) % tabs.length,
    ArrowLeft: (at - 1 + tabs.length) % tabs.length,
    Home: 0,
    End: tabs.length - 1,
  };
  const next = tabs[target[e.key]];
  if (!next) return;
  e.preventDefault();
  next.focus();
  next.click();
}

/** A row of underlined tabs. The active one is the parent's state, as is its panel. */
export function Tabs({ label, children, style }: TabsProps) {
  const c = useColors();
  return (
    <div
      role="tablist"
      aria-label={label}
      onKeyDown={moveAlongTabs}
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
      tabIndex={active ? 0 : -1}
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
