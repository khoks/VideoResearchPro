import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, lineHeight, radius, space } from '../../theme';

/**
 * Why a subscribe or sync started no job (T-5.2.15), in the server's words.
 * Not an error: the subscription stands, and the note says how to start the
 * sync later.
 */
export function SyncNote({ text }: { text: string }) {
  const c = useColors();
  return (
    <div
      role="status"
      data-testid="channel-sync-note"
      style={{
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        lineHeight: lineHeight.normal,
        color: c.textPrimary,
        background: c.surfaceAlt,
        border: `1px solid ${c.border}`,
        borderRadius: radius.md,
        padding: `${space['2']} ${space['3']}`,
      }}
    >
      {text}
    </div>
  );
}
