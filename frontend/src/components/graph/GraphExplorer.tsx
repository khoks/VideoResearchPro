/**
 * The library map (S-8.9.2): filters, the one-paragraph summary, the legend,
 * the canvas or its table, and the detail card. Used full-page at
 * `/library/graph` and, compact and scoped to one channel, as the channel
 * page's concept map. State is controlled so the page can keep it in the URL.
 *
 * Every figure comes from `GET /library/graph`, which only ever sees the
 * reader's visible documents (D-063); nothing here widens that.
 */
import { useEffect, useId, useMemo, useState, type CSSProperties } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, EmptyState, Skeleton } from '../primitives';
import { useElementWidth } from '../charts/useElementWidth';
import { useLibraryGraph } from '../../hooks/useLibraryGraph';
import { useShelves } from '../../hooks/useShelves';
import { useChannel } from '../../hooks/useChannels';
import { useColors, useGroupColors } from '../../hooks/useTheme';
import { fonts, fontSize, lineHeight, space } from '../../theme';
import { apiErrorMessage, isNotFound } from '../../utils/apiError';
import { jobDisplayTitle } from '../../utils/jobTitle';
import { jobsApi } from '../../services/jobsApi';
import { buildModel, type GraphModel } from '../../utils/graphModel';
import { GraphCanvas } from './GraphCanvas';
import { GraphControls, type ExplorerState } from './GraphControls';
import { GraphDetailCard } from './GraphDetailCard';
import { GraphTable } from './GraphTable';

/** Nodes asked for per map: enough to read, few enough to stay legible. */
export const GRAPH_LIMIT = 300;
const NARROW = 640;

function Legend({ model }: { model: GraphModel }) {
  const c = useColors();
  const gc = useGroupColors();
  const coloured = model.groups.filter(g => g.slot !== null);
  const others = model.groups.filter(g => g.slot === null);
  const othersSize = others.reduce((n, g) => n + g.size, 0);
  const item: CSSProperties = {
    display: 'flex',
    alignItems: 'baseline',
    gap: space['2'],
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    color: c.textPrimary,
    lineHeight: lineHeight.snug,
  };
  const dot = (color: string): CSSProperties => ({
    width: 10,
    height: 10,
    borderRadius: '50%',
    background: color,
    flex: '0 0 auto',
    transform: 'translateY(1px)',
  });
  return (
    <div data-graph-legend="" style={{ display: 'flex', flexDirection: 'column', gap: space['1'] }}>
      <ul aria-label="Groups" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexWrap: 'wrap', gap: `${space['1']} ${space['5']}` }}>
        {coloured.map(g => (
          <li key={g.index} style={item}>
            <span aria-hidden="true" style={dot(gc.groups[g.slot!])} />
            <span>
              {g.name} · {g.size} nodes
              {g.about.length > 0 && <span style={{ color: c.textSecondary }}> · {g.about.join(', ')}</span>}
            </span>
          </li>
        ))}
        {othersSize > 0 && (
          <li style={item}>
            <span aria-hidden="true" style={dot(gc.other)} />
            <span>
              {coloured.length ? 'Other groups' : 'Groups'} · {othersSize} {othersSize === 1 ? 'node' : 'nodes'} in {others.length}{' '}
              {others.length === 1 ? 'group' : 'groups'}
            </span>
          </li>
        )}
      </ul>
      <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
        Colour marks a group of closely linked nodes. ▸ channel · # topic · ? your question · no mark: a source. Larger dots
        have more connections.
      </p>
    </div>
  );
}

export function GraphExplorer({
  state,
  onChange,
  compact = false,
  ariaLabel = 'Library map',
}: {
  state: ExplorerState;
  onChange: (next: Partial<ExplorerState>) => void;
  /** The channel page's concept map: shorter, no shelf filter, channel fixed. */
  compact?: boolean;
  ariaLabel?: string;
}) {
  const c = useColors();
  const summaryId = useId();
  const [wrapRef, width] = useElementWidth<HTMLDivElement>();
  const query = useLibraryGraph({
    focus: state.focus,
    depth: state.depth,
    shelfId: state.shelfId,
    channelId: state.channelId,
    jobId: state.jobId,
    types: state.types,
    limit: GRAPH_LIMIT,
  });
  const shelves = useShelves();
  const channel = useChannel(!compact ? state.channelId : null);
  // The run's title for its chip; shares the run cache without useJob's polling.
  const job = useQuery({
    queryKey: ['job', state.jobId],
    queryFn: () => jobsApi.get(state.jobId!),
    enabled: !!state.jobId,
    staleTime: 60_000,
  });
  const data = query.data;
  const model = useMemo(() => (data ? buildModel(data, { hideLeaves: !state.showLeaves }) : null), [data, state.showLeaves]);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (selected && model && !model.byId.has(selected)) setSelected(null);
  }, [model, selected]);

  const view = state.view ?? (width > 0 && width < NARROW ? 'table' : 'map');
  const refocus = (id: string) => {
    setSelected(id);
    onChange({ focus: id });
  };
  const focusLabel = (model && state.focus && model.byId.get(state.focus)?.displayLabel) || null;
  const lostFocus = !!state.focus && !!data && data.focus === null;

  let body;
  if (query.isLoading || !model || !data) {
    body = query.isError ? (
      <EmptyState
        size="sm"
        title={isNotFound(query.error) ? 'Not found' : 'The map did not load'}
        description={
          isNotFound(query.error)
            ? 'That shelf or run is not yours, or it no longer exists.'
            : apiErrorMessage(query.error, 'Try again in a moment.')
        }
        action={
          <Button size="sm" variant="secondary" onClick={() => query.refetch()}>
            Try again
          </Button>
        }
      />
    ) : (
      <Skeleton variant="card" width="100%" height={compact ? 320 : 480} />
    );
  } else if (data.nodes.length === 0) {
    const scoped = !!(state.shelfId || state.channelId || state.jobId);
    body = (
      <EmptyState
        size="sm"
        title="Nothing to map yet"
        description={
          scoped
            ? 'None of your sources falls in this view.'
            : 'The map draws the sources in your library, their channels and topics, and the questions you asked about them. Add sources or run a search, then come back.'
        }
      />
    );
  } else if (model.nodes.length === 0) {
    body = (
      <EmptyState
        size="sm"
        title="Every node here has a single link"
        description="Single-link nodes are hidden to keep the map readable, which leaves nothing in this view."
        action={
          <Button size="sm" variant="secondary" onClick={() => onChange({ showLeaves: true })}>
            Show single-link nodes
          </Button>
        }
      />
    );
  } else {
    const card = selected ? (
      <GraphDetailCard
        model={model}
        id={selected}
        onClose={() => setSelected(null)}
        onRefocus={refocus}
        onSelect={setSelected}
      />
    ) : null;
    body =
      view === 'map' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          <GraphCanvas
            model={model}
            selected={selected}
            onSelect={setSelected}
            onRefocus={refocus}
            ariaLabel={ariaLabel}
            summaryId={summaryId}
            height={compact ? 360 : 560}
          />
          {card}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          {card}
          <GraphTable model={model} selected={selected} onSelect={setSelected} maxHeight={compact ? 360 : 520} />
        </div>
      );
  }

  return (
    <div ref={wrapRef} style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }} data-graph-explorer="">
      <GraphControls
        state={state}
        view={view}
        onChange={onChange}
        shelves={shelves.data}
        hiddenLeaves={model?.hiddenLeaves ?? 0}
        focusLabel={focusLabel}
        channelLabel={channel.data?.name ?? null}
        jobLabel={job.data ? jobDisplayTitle(job.data) : null}
        compact={compact}
      />
      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
          <p
            id={summaryId}
            data-graph-summary=""
            style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, lineHeight: lineHeight.normal, color: c.textPrimary }}
          >
            {lostFocus ? 'The node you asked for is not on your map, so the whole library is shown. ' : ''}
            {data.summary}
            {model && model.hiddenLeaves > 0
              ? ` ${model.hiddenLeaves} single-link ${model.hiddenLeaves === 1 ? 'node is' : 'nodes are'} hidden.`
              : ''}
            {query.isFetching && !query.isLoading ? ' Updating…' : ''}
          </p>
          {model && model.nodes.length > 0 && <Legend model={model} />}
        </div>
      )}
      {body}
    </div>
  );
}
