/**
 * The reading room's loading line: a spinner and "Opening the report…".
 *
 * Each reader shows it while its data loads, and the router shows the same
 * line while the reader's own chunk loads (T-8.8.4.1), so opening a report
 * reads as one wait, not two different ones. The router imports this file
 * directly, never through `./index`, which would pull the sanitiser and the
 * parsers back into the first-paint chunk.
 */
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, space } from '../../theme';
import { Spinner } from '../primitives/Spinner';

export function ReaderLoading({ label }: { label: string }) {
  const c = useColors();
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], color: c.textSecondary }}>
      <Spinner /> <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm }}>{label}</span>
    </div>
  );
}
