import type { CSSProperties } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';

export interface StepperProps {
  steps: string[];
  /** 1-based. */
  current: number;
  /** Steps before `current` that may be revisited. Omit to make them static. */
  onSelect?: (step: number) => void;
}

/**
 * A plain task-flow stepper (S-8.10.1, plan M10: a task flow, not an overlay
 * tour). An ordered list with `aria-current="step"`; earlier steps are
 * buttons so a reader can go back without losing what they entered.
 */
export function Stepper({ steps, current, onSelect }: StepperProps) {
  const c = useColors();
  return (
    <ol
      aria-label="Getting started"
      style={{
        listStyle: 'none',
        margin: 0,
        padding: 0,
        display: 'flex',
        flexWrap: 'wrap',
        gap: space['3'],
      }}
    >
      {steps.map((label, i) => {
        const n = i + 1;
        const done = n < current;
        const here = n === current;
        const dot: CSSProperties = {
          width: 24,
          height: 24,
          flexShrink: 0,
          borderRadius: radius.pill,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          fontWeight: fontWeight.semibold,
          border: `1px solid ${here || done ? c.accent : c.border}`,
          background: here ? c.accent : done ? c.accentSubtle : 'transparent',
          color: here ? c.textInverted : done ? c.accent : c.textMuted,
        };
        const text: CSSProperties = {
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          fontWeight: here ? fontWeight.semibold : fontWeight.regular,
          color: here ? c.textPrimary : c.textSecondary,
        };
        const inner = (
          <>
            <span aria-hidden="true" style={dot}>{done ? '✓' : n}</span>
            <span style={text}>{label}</span>
            {done && <span className="reader-sr-only"> (done)</span>}
          </>
        );
        return (
          <li
            key={label}
            aria-current={here ? 'step' : undefined}
            style={{ display: 'flex', alignItems: 'center', gap: space['2'] }}
          >
            {done && onSelect ? (
              <button
                type="button"
                onClick={() => onSelect(n)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: space['2'],
                  background: 'none',
                  border: 'none',
                  padding: `${space['1']} 0`,
                  minHeight: 44,
                  cursor: 'pointer',
                }}
              >
                {inner}
              </button>
            ) : (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: space['2'], minHeight: 44 }}>{inner}</span>
            )}
            {n < steps.length && (
              <span aria-hidden="true" style={{ width: 24, height: 1, background: c.border }} />
            )}
          </li>
        );
      })}
    </ol>
  );
}
