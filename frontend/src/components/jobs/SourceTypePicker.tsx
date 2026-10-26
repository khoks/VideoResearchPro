import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import {
  isDefaultSourceTypes,
  offeredSourceTypes,
  sourceTypeLabel,
  toggleSourceType,
  unavailableSourceTypes,
  type SourceType,
} from '../../utils/jobForm';

export interface SourceTypePickerProps {
  selected: SourceType[];
  onChange: (next: SourceType[]) => void;
  /** `/health` capabilities; null until the first poll answers. */
  capabilities: Record<string, boolean> | null;
}

/**
 * S-1.5.13 (T-1.5.13.3): which sources a topic run searches. Offers only what
 * this install can search: Reddit, web articles and X / Twitter need an
 * operator credential and appear when `/health` reports it (T-1.5.9.3). A run
 * or template that carried a source the install no longer has shows it struck
 * through, to be removed before submitting, never silently dropped.
 */
export function SourceTypePicker({ selected, onChange, capabilities }: SourceTypePickerProps) {
  const c = useColors();
  const offered = offeredSourceTypes(capabilities);
  const unavailable = unavailableSourceTypes(selected, capabilities);
  const youtube = selected.includes('video');
  const others = selected.some((v) => v !== 'video');

  const chip = (value: SourceType, label: string, on: boolean, broken = false) => (
    <button
      type="button"
      key={value}
      data-source-type={value}
      aria-pressed={on}
      title={broken ? 'Not set up on this install. Click to remove.' : undefined}
      onClick={() => onChange(toggleSourceType(selected, value))}
      style={{
        background: on && !broken ? c.accent : 'transparent',
        color: broken ? c.error : on ? c.textInverted : c.textSecondary,
        border: `1px solid ${broken ? c.error : on ? c.accent : c.borderStrong}`,
        padding: `${space['1']} ${space['3']}`,
        borderRadius: radius.pill,
        fontFamily: fonts.ui,
        fontSize: fontSize.xs,
        cursor: 'pointer',
        fontWeight: on ? fontWeight.semibold : fontWeight.medium,
        letterSpacing: '0.02em',
        textDecoration: broken ? 'line-through' : undefined,
      }}
    >
      {label}
    </button>
  );

  let note: string | null = null;
  if (unavailable.length > 0) {
    note = `${unavailable.map(sourceTypeLabel).join(', ')} ${
      unavailable.length === 1 ? 'is' : 'are'
    } not set up on this install. Remove ${unavailable.length === 1 ? 'it' : 'them'} to submit.`;
  } else if (selected.length === 0) {
    note = 'Choose at least one source to search.';
  } else if (!youtube) {
    note = 'Without YouTube, the duration, preferred-channel and channel-type settings below do not apply.';
  } else if (others) {
    note = 'Each other source returns up to the number of videos you set below.';
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
      <div
        role="group"
        aria-label="Sources to search"
        data-testid="source-type-picker"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: space['2'],
          padding: space['2'],
          border: `1px solid ${c.border}`,
          borderRadius: radius.md,
          background: c.surfaceAlt,
        }}
      >
        {offered.map((o) => chip(o.value, o.label, selected.includes(o.value)))}
        {unavailable.map((v) => chip(v, sourceTypeLabel(v), true, true))}
      </div>
      {note && !isDefaultSourceTypes(selected) && (
        <p
          data-testid="source-type-note"
          role={unavailable.length > 0 || selected.length === 0 ? 'alert' : undefined}
          style={{
            margin: 0,
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            lineHeight: lineHeight.snug,
            color: unavailable.length > 0 || selected.length === 0 ? c.error : c.textSecondary,
          }}
        >
          {note}
        </p>
      )}
    </div>
  );
}
