/**
 * The channel's concept map (S-8.9.2, moved here from T-8.7.3.2): the library
 * map scoped to this channel, inside the Intelligence tab. It loads the graph
 * code only when asked, so opening a channel page never pays for sigma.
 */
import { lazy, Suspense, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, Skeleton } from '../primitives';
import { DEFAULT_EXPLORER_STATE, type ExplorerState } from '../graph/GraphControls';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, lineHeight, space } from '../../theme';

const GraphExplorer = lazy(() => import('../graph/GraphExplorer').then(m => ({ default: m.GraphExplorer })));

export function ConceptMap({ channelId }: { channelId: string }) {
  const c = useColors();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<ExplorerState>({
    ...DEFAULT_EXPLORER_STATE,
    channelId,
    types: ['topic', 'exchange'],
  });

  const onChange = (next: Partial<ExplorerState>) =>
    setState(s => {
      const merged = { ...s, ...next, channelId };
      if ('focus' in next && next.focus !== s.focus) merged.depth = next.depth ?? 1;
      return merged;
    });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
      <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.snug }}>
        How this channel's topics connect through the sources of it you can see, and the questions you asked about them.
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: space['4'] }}>
        {!open && (
          <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
            Show the concept map
          </Button>
        )}
        <Link to={`/library/graph?channel_id=${encodeURIComponent(channelId)}`} style={{ color: c.accent, fontFamily: fonts.ui, fontSize: fontSize.sm }}>
          Open in the library map
        </Link>
      </div>
      {open && (
        <Suspense fallback={<Skeleton variant="card" width="100%" height={360} />}>
          <GraphExplorer compact state={state} onChange={onChange} ariaLabel="Concept map of this channel" />
        </Suspense>
      )}
    </div>
  );
}
