/**
 * `/library/graph` — the library map (S-8.9.2). Loaded lazily: sigma,
 * graphology and the layout worker only download when this page (or a
 * channel's concept map) opens. The map's state lives in the URL, so a view
 * can be bookmarked, shared with yourself, and walked back with Back:
 *
 *   ?focus=<node id>&depth=1..3   the neighbourhood of one node
 *   ?shelf_id= &channel_id= &job_id=
 *   ?types=channel,topic,exchange  kinds besides sources ("none" for sources only)
 *   ?leaves=1                      show single-link nodes
 *   ?view=map|table
 */
import { useSearchParams } from 'react-router-dom';
import { GraphExplorer } from '../components/graph/GraphExplorer';
import { DEFAULT_EXPLORER_STATE, type ExplorerState } from '../components/graph/GraphControls';
import { useColors } from '../hooks/useTheme';
import { GRAPH_EXTRA_TYPES, type GraphExtraType } from '../services/graphApi';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../theme';

function readState(params: URLSearchParams): ExplorerState {
  const rawTypes = params.get('types');
  const types: GraphExtraType[] | null =
    rawTypes === null
      ? null
      : rawTypes === 'none'
        ? []
        : GRAPH_EXTRA_TYPES.filter(t => rawTypes.split(',').includes(t));
  const depth = Number(params.get('depth'));
  const view = params.get('view');
  return {
    focus: params.get('focus'),
    depth: depth >= 1 && depth <= 3 ? Math.round(depth) : DEFAULT_EXPLORER_STATE.depth,
    shelfId: params.get('shelf_id'),
    channelId: params.get('channel_id'),
    jobId: params.get('job_id'),
    types,
    showLeaves: params.get('leaves') === '1',
    view: view === 'map' || view === 'table' ? view : null,
  };
}

function writeState(s: ExplorerState): URLSearchParams {
  const p = new URLSearchParams();
  if (s.focus) {
    p.set('focus', s.focus);
    if (s.depth !== 1) p.set('depth', String(s.depth));
  }
  if (s.shelfId) p.set('shelf_id', s.shelfId);
  if (s.channelId) p.set('channel_id', s.channelId);
  if (s.jobId) p.set('job_id', s.jobId);
  if (s.types) p.set('types', s.types.length ? s.types.join(',') : 'none');
  if (s.showLeaves) p.set('leaves', '1');
  if (s.view) p.set('view', s.view);
  return p;
}

export default function GraphPage() {
  const c = useColors();
  const [params, setParams] = useSearchParams();
  const state = readState(params);

  const onChange = (next: Partial<ExplorerState>) => {
    const merged = { ...state, ...next };
    if ('focus' in next && next.focus !== state.focus) merged.depth = next.depth ?? 1;
    // A new centre is a step Back can undo; filter tweaks replace the entry.
    setParams(writeState(merged), { replace: !('focus' in next) || next.focus === state.focus });
  };

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
      <header style={{ marginBottom: space['5'] }}>
        <h1
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            margin: 0,
            lineHeight: lineHeight.tight,
          }}
        >
          Library map
        </h1>
        <p
          style={{
            fontFamily: fonts.body,
            fontStyle: 'italic',
            fontSize: fontSize.sm,
            color: c.textMuted,
            margin: `${space['2']} 0 0`,
          }}
        >
          Your sources, the channels and topics that join them, and the questions you asked of them.
        </p>
      </header>
      <GraphExplorer state={state} onChange={onChange} />
    </div>
  );
}
