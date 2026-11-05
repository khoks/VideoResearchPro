import type { ComponentPropsWithRef } from 'react';

export interface IconButtonProps extends Omit<ComponentPropsWithRef<'button'>, 'aria-label'> {
  /** The button's name for a screen reader: it shows no text of its own. */
  label: string;
}

/**
 * A bare glyph that acts as a button, such as the × on a chip or the bell in
 * the top bar. Transparent and borderless, so it sits on any surface; each
 * place sets its own size and colour through `style`. A bordered control with
 * a glyph in it is a `Button`.
 */
export function IconButton({ label, type = 'button', style, ...rest }: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      style={{ background: 'transparent', border: 'none', cursor: 'pointer', ...style }}
      {...rest}
    />
  );
}
