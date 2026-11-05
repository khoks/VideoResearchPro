import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import type { SourceHold } from '../../stores/systemStatusStore';
import {
  heldSourcesNote,
  isDefaultSourceTypes,
  offeredSourceTypes,
  sourceTypeLabel,
  sourceTypeShares,
  toggleSourceType,
  unavailableSourceTypes,
  type SourceType,
} from '../../utils/jobForm';

export interface SourceTypePickerProps {
  selected: SourceType[];
  onChange: (next: SourceType[]) => void;
  /** `/health` capabilities; null until the first poll answers. */
  capabilities: Record<string, boolean> | null;
  /** The run's `num_videos`, shared across the chosen sources. */
  numVideos: number;
  /** Sources that refused this install, from `/health` (T-1.5.14.1). */
  holds?: Record<string, SourceHold>;
}

/**
 * S-1.5.13 (T-1.5.13.3): which sources a topic run searches. Offers only what
 * this install can search: Reddit, web articles and X / Twitter need an
 * operator credential and appear when `/health` reports it (T-1.5.9.3). A run
 * or template that carried a source the install no longer has shows it struck
 * through, to be removed before submitting, never silently dropped. The run's
 * `num_videos` is shared across the chosen sources (the plan cap bounds the
 * whole run), and the note says how it splits. A source that refused this
 * install drops out, and a second note says why, so it never just vanishes.
 */
export function SourceTypePicker({ selected, onChange, capabilities, numVideos, holds = {} }: SourceTypePickerProps) {
  const c = useColors();
  const offered = offeredSourceTypes(capabilities);
  const unavailable = unavailableSourceTypes(selected, capabilities);
  const youtube = selected.includes('video');
  const tooFew = selected.length > 1 && numVideos < selected.length;

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
  } else if (tooFew) {
    note = `Ask for at least ${selected.length} results below, one per source.`;
  } else {
    const parts: string[] = [];
    if (selected.length > 1) {
      const shares = sourceTypeShares(numVideos, selected);
      parts.push(
        `The ${numVideos} results you set below are shared across these sources: ${selected
          .map((v) => `${sourceTypeLabel(v)} ${shares[v] ?? 0}`)
          .join(', ')}. A source that comes back short passes its share to the others.`,
      );
    }
    if (!youtube) {
      parts.push('Without YouTube, the duration, preferred-channel and channel-type settings below do not apply.');
    }
    note = parts.length > 0 ? parts.join(' ') : null;
  }
  const alert = unavailable.length > 0 || selected.length === 0 || tooFew;
  const heldNote = heldSourcesNote(holds);

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
          role={alert ? 'alert' : undefined}
          style={{
            margin: 0,
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            lineHeight: lineHeight.snug,
            color: alert ? c.error : c.textSecondary,
          }}
        >
          {note}
        </p>
      )}
      {heldNote && (
        <p
          data-testid="source-type-held-note"
          style={{
            margin: 0,
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            lineHeight: lineHeight.snug,
            color: c.textSecondary,
          }}
        >
          {heldNote}
        </p>
      )}
    </div>
  );
}
