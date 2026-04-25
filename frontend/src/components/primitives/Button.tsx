import { forwardRef, useState, type ButtonHTMLAttributes, type CSSProperties, type ReactNode } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space, motion } from '../../theme';

export type ButtonVariant = 'primary' | 'secondary' | 'tertiary' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'style'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
  fullWidth?: boolean;
  style?: CSSProperties;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    size = 'md',
    loading = false,
    leadingIcon,
    trailingIcon,
    fullWidth = false,
    disabled,
    children,
    style,
    onMouseEnter,
    onMouseLeave,
    onFocus,
    onBlur,
    ...rest
  },
  ref,
) {
  const c = useColors();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const isDisabled = disabled || loading;

  const sizeStyles: Record<ButtonSize, CSSProperties> = {
    sm: { padding: `${space['1']} ${space['3']}`, fontSize: fontSize.sm, minHeight: 30 },
    md: { padding: `${space['2']} ${space['4']}`, fontSize: fontSize.base, minHeight: 38 },
    lg: { padding: `${space['3']} ${space['5']}`, fontSize: fontSize.md, minHeight: 44 },
  };

  const variantStyles: Record<ButtonVariant, CSSProperties> = {
    primary: {
      background: hovered && !isDisabled ? c.accent : c.accent,
      color: c.textInverted,
      border: `1px solid ${c.accent}`,
      filter: hovered && !isDisabled ? 'brightness(1.08)' : 'none',
    },
    secondary: {
      background: c.surface,
      color: c.accent,
      border: `1px solid ${hovered && !isDisabled ? c.accent : c.border}`,
    },
    tertiary: {
      background: 'transparent',
      color: c.accent,
      border: '1px solid transparent',
      textDecoration: hovered && !isDisabled ? 'underline' : 'none',
      textUnderlineOffset: 3,
    },
    danger: {
      background: c.error,
      color: c.textInverted,
      border: `1px solid ${c.error}`,
      filter: hovered && !isDisabled ? 'brightness(1.08)' : 'none',
    },
  };

  const base: CSSProperties = {
    fontFamily: fonts.ui,
    fontWeight: fontWeight.medium,
    borderRadius: radius.md,
    cursor: isDisabled ? 'not-allowed' : 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space['2'],
    width: fullWidth ? '100%' : 'auto',
    opacity: isDisabled ? 0.55 : 1,
    transition: `background-color ${motion.duration.fast}ms ${motion.easing.standard}, border-color ${motion.duration.fast}ms ${motion.easing.standard}, filter ${motion.duration.fast}ms ${motion.easing.standard}`,
    outline: focused ? `2px solid ${c.focus}` : 'none',
    outlineOffset: 2,
    userSelect: 'none',
    whiteSpace: 'nowrap',
  };

  return (
    <button
      ref={ref}
      disabled={isDisabled}
      style={{ ...base, ...sizeStyles[size], ...variantStyles[variant], ...style }}
      onMouseEnter={(e) => {
        setHovered(true);
        onMouseEnter?.(e);
      }}
      onMouseLeave={(e) => {
        setHovered(false);
        onMouseLeave?.(e);
      }}
      onFocus={(e) => {
        setFocused(true);
        onFocus?.(e);
      }}
      onBlur={(e) => {
        setFocused(false);
        onBlur?.(e);
      }}
      {...rest}
    >
      {loading ? <InlineSpinner /> : leadingIcon}
      {children}
      {!loading && trailingIcon}
    </button>
  );
});

function InlineSpinner() {
  const c = useColors();
  return (
    <span
      aria-hidden
      style={{
        width: 14,
        height: 14,
        borderRadius: '50%',
        border: `2px solid ${c.textInverted}`,
        borderTopColor: 'transparent',
        animation: 'spin 700ms linear infinite',
      }}
    />
  );
}
