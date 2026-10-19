/**
 * Filters for the library map (S-8.9.2), in one row above it: view (map or
 * table), node kinds, shelf, single-link nodes, and the current scope
 * (centred node with its depth, channel, run) as removable chips.
 */
import { type CSSProperties, type ReactNode } from 'react';
import { Button, Select } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';
import { GRAPH_EXTRA_TYPES, type GraphExtraType } from '../../services/graphApi';
import type { Shelf } from '../../services/shelvesApi';

export interface ExplorerState {
  /** A node id: the map shows its neighbourhood. */
  focus: string | null;
  depth: number;
  shelfId: string | null;
  channelId: string | null;
  jobId: string | null;
  /** Kinds besides sources; null means all of them. */
  types: GraphExtraType[] | null;
  showLeaves: boolean;
  /** Null picks by width: the table below 640 px, the map above. */
  view: 'map' | 'table' | null;
}

export const DEFAULT_EXPLORER_STATE: ExplorerState = {
  focus: null,
  depth: 1,
  shelfId: null,
  channelId: null,
  jobId: null,
  types: null,
  showLeaves: false,
  view: null,
};

const KIND_LABEL: Record<GraphExtraType, string> = {
  channel: '▸ Channels',
  topic: '# Topics',
  exchange: '? Your questions',
};

export function GraphControls({
  state,
  view,
  onChange,
  shelves,
  hiddenLeaves,
  focusLabel,
  channelLabel,
  jobLabel,
  compact,
}: {
  state: ExplorerState;
  view: 'map' | 'table';
  onChange: (next: Partial<ExplorerState>) => void;
  shelves: Shelf[] | undefined;
  hiddenLeaves: number;
  focusLabel: string | null;
  channelLabel: string | null;
  jobLabel: string | null;
  compact: boolean;
}) {
  const c = useColors();
  const types = state.types ?? GRAPH_EXTRA_TYPES;
  const label: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: space['1'],
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    color: c.textPrimary,
    cursor: 'pointer',
  };
  const groupLabel: CSSProperties = {
    fontFamily: fonts.ui,
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
    color: c.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  };

  const toggleType = (t: GraphExtraType) => {
    const next = types.includes(t) ? types.filter(x => x !== t) : [...types, t];
    onChange({ types: next.length === GRAPH_EXTRA_TYPES.length ? null : GRAPH_EXTRA_TYPES.filter(x => next.includes(x)) });
  };

  const chip = (key: string, content: ReactNode, onRemove: () => void, removeLabel: string) => (
    <span
      key={key}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: space['2'],
        padding: `${space['1']} ${space['2']}`,
        borderRadius: radius.pill,
        background: c.surfaceAlt,
        border: `1px solid ${c.border}`,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        color: c.textPrimary,
        maxWidth: '100%',
      }}
    >
      <span style={{ overflowWrap: 'anywhere' }}>{content}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={removeLabel}
        title={removeLabel}
        style={{
          background: 'none',
          border: 'none',
          padding: `0 ${space['1']}`,
          minWidth: 24,
          minHeight: 24,
          cursor: 'pointer',
          color: c.textSecondary,
          fontSize: fontSize.base,
        }}
      >
        <span aria-hidden="true">×</span>
      </button>
    </span>
  );

  const chips: ReactNode[] = [];
  if (state.focus) {
    chips.push(
      chip(
        'focus',
        <>
          Centred on <strong style={{ fontWeight: fontWeight.semibold }}>{focusLabel ?? 'a node'}</strong>
        </>,
        () => onChange({ focus: null }),
        'Show the whole map again',
      ),
    );
  }
  if (state.channelId && !compact) {
    chips.push(chip('channel', <>Channel: {channelLabel ?? state.channelId}</>, () => onChange({ channelId: null }), 'Remove the channel filter'));
  }
  if (state.jobId) {
    chips.push(chip('job', <>Run: {jobLabel ?? 'one run'}</>, () => onChange({ jobId: null }), 'Remove the run filter'));
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: `${space['3']} ${space['5']}` }}>
        <div role="group" aria-label="View" style={{ display: 'inline-flex', gap: space['1'] }}>
          <Button size="sm" variant={view === 'map' ? 'primary' : 'secondary'} aria-pressed={view === 'map'} onClick={() => onChange({ view: 'map' })}>
            Map
          </Button>
          <Button size="sm" variant={view === 'table' ? 'primary' : 'secondary'} aria-pressed={view === 'table'} onClick={() => onChange({ view: 'table' })}>
            Table
          </Button>
        </div>

        <fieldset style={{ border: 'none', margin: 0, padding: 0, display: 'inline-flex', flexWrap: 'wrap', alignItems: 'center', gap: space['3'] }}>
          <legend style={{ ...groupLabel, float: 'left', marginRight: space['2'] }}>Show</legend>
          {GRAPH_EXTRA_TYPES.map(t => (
            <label key={t} style={label}>
              <input type="checkbox" checked={types.includes(t)} onChange={() => toggleType(t)} style={{ accentColor: c.accent }} />
              {KIND_LABEL[t]}
            </label>
          ))}
        </fieldset>

        {!compact && shelves && shelves.length > 0 && (
          <label style={{ ...label, cursor: 'default' }}>
            <span style={groupLabel}>Shelf</span>
            <Select
              value={state.shelfId ?? ''}
              onChange={e => onChange({ shelfId: e.target.value || null })}
              style={{ width: 'auto', minWidth: 160 }}
            >
              <option value="">Whole library</option>
              {shelves.map(s => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </label>
        )}

        {!state.focus && (
          <label style={label}>
            <input
              type="checkbox"
              checked={state.showLeaves}
              onChange={e => onChange({ showLeaves: e.target.checked })}
              style={{ accentColor: c.accent }}
            />
            Single-link nodes
            {!state.showLeaves && hiddenLeaves > 0 ? <span style={{ color: c.textMuted }}>({hiddenLeaves} hidden)</span> : null}
          </label>
        )}
      </div>

      {(chips.length > 0 || state.focus) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: space['3'] }}>
          {chips}
          {state.focus && (
            <label style={{ ...label, cursor: 'default' }}>
              <span style={groupLabel}>Depth</span>
              <input
                type="range"
                min={1}
                max={3}
                step={1}
                value={state.depth}
                onChange={e => onChange({ depth: Number(e.target.value) })}
                aria-valuetext={`${state.depth} ${state.depth === 1 ? 'step' : 'steps'} out`}
                style={{ accentColor: c.accent }}
              />
              <span style={{ color: c.textSecondary, fontVariantNumeric: 'tabular-nums' }}>
                {state.depth} {state.depth === 1 ? 'step' : 'steps'} out
              </span>
            </label>
          )}
        </div>
      )}
    </div>
  );
}
