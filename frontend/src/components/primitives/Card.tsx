import { forwardRef, useState, type CSSProperties, type HTMLAttributes, type ReactNode } from 'react';
import { useColors, useShadows } from '../../hooks/useTheme';
import { radius, space, motion } from '../../theme';

export interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, 'style'> {
  /** Adds a 2 px lift + subtle shadow on hover. Use for clickable cards only. */
  interactive?: boolean;
  /** Sunken variant — uses surfaceAlt fill. */
  sunken?: boolean;
  /** Removes padding; caller supplies it. Useful for cards with a full-bleed image. */
  flush?: boolean;
  children?: ReactNode;
  style?: CSSProperties;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { interactive = false, sunken = false, flush = false, children, style, onMouseEnter, onMouseLeave, ...rest },
  ref,
) {
  const c = useColors();
  const s = useShadows();
  const [hovered, setHovered] = useState(false);

  const base: CSSProperties = {
    background: sunken ? c.surfaceAlt : c.surface,
    border: `1px solid ${c.border}`,
    borderRadius: radius.md,
    padding: flush ? 0 : space['5'],
    transition: `transform ${motion.duration.fast}ms ${motion.easing.standard}, box-shadow ${motion.duration.fast}ms ${motion.easing.standard}, border-color ${motion.duration.fast}ms ${motion.easing.standard}`,
    boxShadow: interactive && hovered ? s.hover : s.none,
    transform: interactive && hovered ? 'translateY(-2px)' : 'translateY(0)',
    borderColor: interactive && hovered ? c.borderStrong : c.border,
    cursor: interactive ? 'pointer' : 'default',
  };

  return (
    <div
      ref={ref}
      style={{ ...base, ...style }}
      onMouseEnter={(e) => {
        if (interactive) setHovered(true);
        onMouseEnter?.(e);
      }}
      onMouseLeave={(e) => {
        if (interactive) setHovered(false);
        onMouseLeave?.(e);
      }}
      {...rest}
    >
      {children}
    </div>
  );
});
