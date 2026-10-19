import { PALETTE_COLORS, type PaletteColor } from '../../theme';
import { useColors, usePaletteColor } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';

/** A radio group of the ten label-palette colours, each swatch named. */
export function PaletteField({
  value,
  onChange,
  label = 'Colour',
}: {
  value: PaletteColor;
  onChange: (c: PaletteColor) => void;
  label?: string;
}) {
  const c = useColors();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['1'] }}>
      <span
        style={{
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          fontWeight: fontWeight.medium,
          color: c.textSecondary,
        }}
      >
        {label}
      </span>
      <div role="radiogroup" aria-label={label} style={{ display: 'flex', flexWrap: 'wrap', gap: space['2'] }}>
        {PALETTE_COLORS.map((col) => (
          <Swatch key={col} color={col} selected={col === value} onSelect={() => onChange(col)} />
        ))}
      </div>
    </div>
  );
}

function Swatch({
  color,
  selected,
  onSelect,
}: {
  color: PaletteColor;
  selected: boolean;
  onSelect: () => void;
}) {
  const c = useColors();
  const p = usePaletteColor(color);
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: space['1'],
        padding: `2px ${space['2']}`,
        borderRadius: radius.pill,
        background: p.bg,
        color: p.fg,
        border: `${selected ? 2 : 1}px solid ${selected ? c.focus : p.fg}`,
        fontFamily: fonts.ui,
        fontSize: fontSize.xs,
        fontWeight: selected ? fontWeight.semibold : fontWeight.medium,
        cursor: 'pointer',
        textTransform: 'capitalize',
      }}
    >
      {color}
    </button>
  );
}
