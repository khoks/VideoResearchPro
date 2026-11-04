import type { ReactNode } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, space } from '../../theme';

/** A card heading on the account security page. */
export function SectionTitle({ children }: { children: ReactNode }) {
  const c = useColors();
  return (
    <h2
      style={{
        margin: `0 0 ${space['2']}`,
        fontFamily: fonts.display,
        fontSize: fontSize.lg,
        fontWeight: fontWeight.semibold,
        color: c.textPrimary,
      }}
    >
      {children}
    </h2>
  );
}
