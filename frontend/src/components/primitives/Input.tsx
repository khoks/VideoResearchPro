import { forwardRef, useState, type CSSProperties, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, radius, space, motion } from '../../theme';

/** Shared visual shape for Input / Textarea / Select. */
function useFieldStyles(options: { invalid?: boolean; disabled?: boolean; focused: boolean; hovered: boolean }): CSSProperties {
  const c = useColors();
  const { invalid, disabled, focused, hovered } = options;
  const borderColor = invalid
    ? c.error
    : focused
    ? c.accent
    : hovered
    ? c.borderStrong
    : c.border;
  return {
    width: '100%',
    padding: `${space['2']} ${space['3']}`,
    fontFamily: fonts.ui,
    fontSize: fontSize.base,
    background: disabled ? c.surfaceAlt : c.surface,
    color: disabled ? c.textMuted : c.textPrimary,
    border: `1px solid ${borderColor}`,
    borderRadius: radius.md,
    outline: focused ? `2px solid ${invalid ? c.error : c.focus}` : 'none',
    outlineOffset: 1,
    transition: `border-color ${motion.duration.fast}ms ${motion.easing.standard}, outline-color ${motion.duration.fast}ms ${motion.easing.standard}`,
    cursor: disabled ? 'not-allowed' : 'text',
  };
}

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'style'> {
  invalid?: boolean;
  style?: CSSProperties;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { invalid, disabled, style, onFocus, onBlur, onMouseEnter, onMouseLeave, ...rest },
  ref,
) {
  const [focused, setFocused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const base = useFieldStyles({ invalid, disabled, focused, hovered });
  return (
    <input
      ref={ref}
      disabled={disabled}
      aria-invalid={invalid || undefined}
      style={{ ...base, ...style }}
      onFocus={(e) => { setFocused(true); onFocus?.(e); }}
      onBlur={(e) => { setFocused(false); onBlur?.(e); }}
      onMouseEnter={(e) => { setHovered(true); onMouseEnter?.(e); }}
      onMouseLeave={(e) => { setHovered(false); onMouseLeave?.(e); }}
      {...rest}
    />
  );
});

export interface TextareaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'style'> {
  invalid?: boolean;
  style?: CSSProperties;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { invalid, disabled, style, onFocus, onBlur, onMouseEnter, onMouseLeave, rows = 4, ...rest },
  ref,
) {
  const [focused, setFocused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const base = useFieldStyles({ invalid, disabled, focused, hovered });
  return (
    <textarea
      ref={ref}
      rows={rows}
      disabled={disabled}
      aria-invalid={invalid || undefined}
      style={{ ...base, resize: 'vertical', lineHeight: 1.55, ...style }}
      onFocus={(e) => { setFocused(true); onFocus?.(e); }}
      onBlur={(e) => { setFocused(false); onBlur?.(e); }}
      onMouseEnter={(e) => { setHovered(true); onMouseEnter?.(e); }}
      onMouseLeave={(e) => { setHovered(false); onMouseLeave?.(e); }}
      {...rest}
    />
  );
});

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'style'> {
  invalid?: boolean;
  style?: CSSProperties;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { invalid, disabled, style, onFocus, onBlur, onMouseEnter, onMouseLeave, children, ...rest },
  ref,
) {
  const [focused, setFocused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const base = useFieldStyles({ invalid, disabled, focused, hovered });
  return (
    <select
      ref={ref}
      disabled={disabled}
      aria-invalid={invalid || undefined}
      style={{ ...base, cursor: disabled ? 'not-allowed' : 'pointer', ...style }}
      onFocus={(e) => { setFocused(true); onFocus?.(e); }}
      onBlur={(e) => { setFocused(false); onBlur?.(e); }}
      onMouseEnter={(e) => { setHovered(true); onMouseEnter?.(e); }}
      onMouseLeave={(e) => { setHovered(false); onMouseLeave?.(e); }}
      {...rest}
    >
      {children}
    </select>
  );
});
