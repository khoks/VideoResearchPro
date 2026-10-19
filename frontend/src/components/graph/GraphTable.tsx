/**
 * The library map as tables (S-8.9.2): the same nodes the canvas draws
 * (`tableNodes` is built from the same model) and every connection between
 * them. It is the accessible equivalent of the canvas and the default view
 * on narrow screens. A node's name opens the same detail card the map does.
 */
import { useState, type CSSProperties } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, space } from '../../theme';
import { EDGE_NAME, TYPE_NAME, neighbourLabels, tableNodes, type GraphModel } from '../../utils/graphModel';

const MAX_NEIGHBOURS = 4;

export function GraphTable({
  model,
  selected,
  onSelect,
  maxHeight = 520,
}: {
  model: GraphModel;
  selected: string | null;
  onSelect: (id: string) => void;
  maxHeight?: number;
}) {
  const c = useColors();
  const [showEdges, setShowEdges] = useState(false);
  const rows = tableNodes(model);
  const cell: CSSProperties = {
    padding: `${space['1']} ${space['2']}`,
    borderBottom: `1px solid ${c.border}`,
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    color: c.textPrimary,
    textAlign: 'left',
    verticalAlign: 'top',
  };
  const head: CSSProperties = {
    ...cell,
    fontWeight: fontWeight.semibold,
    color: c.textSecondary,
    position: 'sticky',
    top: 0,
    background: c.surface,
  };
  const caption: CSSProperties = {
    textAlign: 'left',
    fontFamily: fonts.ui,
    fontSize: fontSize.xs,
    color: c.textMuted,
    paddingBottom: space['1'],
  };
  const nameButton: CSSProperties = {
    background: 'none',
    border: 'none',
    padding: 0,
    font: 'inherit',
    color: c.accent,
    textDecoration: 'underline',
    textUnderlineOffset: 2,
    cursor: 'pointer',
    textAlign: 'left',
  };

  return (
    <div data-graph-table="">
      <div style={{ maxHeight, overflow: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <caption style={caption}>
            {rows.length} {rows.length === 1 ? 'node' : 'nodes'} on the map, most connected first
          </caption>
          <thead>
            <tr>
              <th scope="col" style={head}>Name</th>
              <th scope="col" style={head}>Kind</th>
              <th scope="col" style={head}>Group</th>
              <th scope="col" style={{ ...head, textAlign: 'right' }}>Links</th>
              <th scope="col" style={head}>Connected to</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(n => {
              const names = neighbourLabels(model, n.id);
              const more = names.length - MAX_NEIGHBOURS;
              return (
                <tr key={n.id} data-node-id={n.id} style={n.id === selected ? { background: c.surfaceAlt } : undefined}>
                  <th scope="row" style={{ ...cell, fontWeight: fontWeight.regular }}>
                    <button
                      type="button"
                      style={nameButton}
                      aria-pressed={n.id === selected}
                      onClick={() => onSelect(n.id)}
                    >
                      {n.displayLabel}
                    </button>
                  </th>
                  <td style={cell}>{TYPE_NAME[n.type]}</td>
                  <td style={cell}>{model.groups[n.group]?.name}</td>
                  <td style={{ ...cell, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{n.shownDegree}</td>
                  <td style={{ ...cell, color: c.textSecondary }}>
                    {names.slice(0, MAX_NEIGHBOURS).join(' · ')}
                    {more > 0 ? ` · and ${more} more` : ''}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <button
        type="button"
        aria-expanded={showEdges}
        onClick={() => setShowEdges(v => !v)}
        style={{ ...nameButton, marginTop: space['3'], fontFamily: fonts.ui, fontSize: fontSize.sm }}
      >
        {showEdges ? 'Hide' : 'Show'} all {model.edges.length} connections
      </button>
      {showEdges && (
        <div style={{ maxHeight, overflow: 'auto', marginTop: space['2'] }}>
          <table style={{ borderCollapse: 'collapse', width: '100%' }} data-graph-edges="">
            <caption style={caption}>Every connection on the map</caption>
            <thead>
              <tr>
                <th scope="col" style={head}>From</th>
                <th scope="col" style={head}>Relation</th>
                <th scope="col" style={head}>To</th>
              </tr>
            </thead>
            <tbody>
              {model.edges.map(e => (
                <tr key={`${e.source}|${e.target}|${e.type}`}>
                  <td style={cell}>{model.byId.get(e.source)?.displayLabel}</td>
                  <td style={{ ...cell, color: c.textSecondary }}>
                    {EDGE_NAME[e.type]}
                    {e.type === 'co_occurs' && e.weight > 1 ? ` (${e.weight} sources)` : ''}
                  </td>
                  <td style={cell}>{model.byId.get(e.target)?.displayLabel}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
