/**
 * The library map's canvas (S-8.9.2): sigma 4 (WebGL) over a graphology
 * graph, laid out by ForceAtlas2 in a web worker and frozen once it settles.
 *
 * A canvas has no DOM, so the accessibility layer is built here, not left to
 * polish (M9 plan): the map is one tab stop; arrow keys move a keyboard focus
 * between nodes (neighbours first, then the nearest node that way); Enter
 * opens the node's card, Escape closes it; + / − / 0 zoom, Shift + arrows
 * pan, and every drag or wheel gesture has a button (WCAG 2.5.7). A ring is
 * drawn over the focused node and a live region names it. Reduced motion
 * computes the layout up front and moves the camera without animation.
 */
import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import Graph from 'graphology';
import Sigma from 'sigma';
import type { EdgeDisplayData, NodeDisplayData } from 'sigma/types';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import FA2Layout from 'graphology-layout-forceatlas2/worker';
import { Button } from '../primitives';
import { useColors, useGroupColors } from '../../hooks/useTheme';
import { fonts, fontSize, radius, space } from '../../theme';
import {
  describeNode,
  nodeInDirection,
  startNode,
  type Direction,
  type GraphModel,
} from '../../utils/graphModel';

export interface GraphCanvasProps {
  model: GraphModel;
  /** The node whose card is open. */
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** Re-centre the map on a node (double-click). */
  onRefocus: (id: string) => void;
  ariaLabel: string;
  /** Id of the paragraph that summarises the map in words. */
  summaryId?: string;
  height: number;
}

const visuallyHidden: CSSProperties = {
  position: 'absolute',
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: 'hidden',
  clip: 'rect(0, 0, 0, 0)',
  whiteSpace: 'nowrap',
  border: 0,
};

const ARROWS: Record<string, Direction> = {
  ArrowUp: 'up',
  ArrowDown: 'down',
  ArrowLeft: 'left',
  ArrowRight: 'right',
};

const PAN_STEP = 0.15;

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

interface Styling {
  selected: string | null;
  active: string | null;
  highlight: Set<string> | null;
  groups: readonly string[];
  other: string;
  edge: string;
  edgeStrong: string;
  text: string;
  surface: string;
}

export function GraphCanvas({ model, selected, onSelect, onRefocus, ariaLabel, summaryId, height }: GraphCanvasProps) {
  const c = useColors();
  const gc = useGroupColors();
  const hintId = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [hasFocus, setHasFocus] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const [layout, setLayout] = useState<'running' | 'settled'>('settled');
  const [ring, setRing] = useState<{ x: number; y: number; r: number } | null>(null);

  const styling = useRef<Styling>({
    selected: null,
    active: null,
    highlight: null,
    groups: gc.groups,
    other: gc.other,
    edge: gc.edge,
    edgeStrong: gc.edgeStrong,
    text: c.textPrimary,
    surface: c.surface,
  });

  const modelRef = useRef(model);
  modelRef.current = model;
  const handlers = useRef({ onSelect, onRefocus });
  handlers.current = { onSelect, onRefocus };

  // Build the renderer and run the layout whenever the map's data changes.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const graph = new Graph({ type: 'undirected', multi: false });
    for (const n of model.nodes) {
      const slot = model.groups[n.group]?.slot ?? null;
      graph.addNode(n.id, { x: n.x, y: n.y, size: n.size, label: n.displayLabel, slot });
    }
    for (const e of model.edges) {
      if (!graph.hasEdge(e.source, e.target)) graph.addEdge(e.source, e.target, { size: 1 });
    }

    const nodeReducer = (key: string, _data: NodeDisplayData, attrs: Record<string, unknown>): Partial<NodeDisplayData> => {
      const s = styling.current;
      const slot = attrs.slot as number | null;
      const out: Partial<NodeDisplayData> = {
        color: slot === null || slot === undefined ? s.other : s.groups[slot],
        labelColor: s.text,
        labelFont: fonts.ui,
        labelSize: 12,
        backdropColor: s.surface,
        backdropShadowColor: 'rgba(0, 0, 0, 0.25)',
      };
      if (s.highlight && !s.highlight.has(key)) {
        out.color = s.edge;
        out.labelVisibility = 'hidden';
      }
      if (key === s.selected || key === s.active) {
        out.labelVisibility = 'visible';
        out.highlighted = true;
        out.depth = 'topNodes';
      }
      return out;
    };
    const edgeReducer = (key: string): Partial<EdgeDisplayData> => {
      const s = styling.current;
      if (!s.selected) return { color: s.edge };
      const [a, b] = graph.extremities(key);
      if (a === s.selected || b === s.selected) return { color: s.edgeStrong, size: 2, depth: 'topEdges' };
      return { color: s.edge, opacity: 0.35 };
    };

    const sigma = new Sigma(graph, container, {
      settings: {
        // sigma 4 measures sizes in graph units by default; the model's sizes are pixels.
        itemSizesReference: 'screen',
        renderEdgeLabels: false,
        labelDensity: 0.6,
        labelRenderedSizeThreshold: 9,
        hideEdgesOnMove: model.edges.length > 1500,
        stagePadding: 24,
        minCameraRatio: 0.05,
        maxCameraRatio: 4,
        enableNodeDrag: false,
        gestureTarget: 'shared',
      },
      nodeReducer,
      edgeReducer,
    });
    sigmaRef.current = sigma;

    sigma.on('clickNode', ({ node }) => {
      setActive(node);
      handlers.current.onSelect(node);
    });
    sigma.on('doubleClickNode', ({ node, event }) => {
      event.preventSigmaDefault();
      handlers.current.onRefocus(node);
    });
    sigma.on('clickStage', () => handlers.current.onSelect(null));
    sigma.on('enterNode', () => {
      container.style.cursor = 'pointer';
    });
    sigma.on('leaveNode', () => {
      container.style.cursor = '';
    });

    // Layout: ForceAtlas2 in a worker, stopped once it has had time to
    // settle; with reduced motion, computed before the first frame instead.
    const settings = { ...forceAtlas2.inferSettings(graph), barnesHutOptimize: graph.order > 400, slowDown: 4 };
    let worker: FA2Layout | null = null;
    let timer: number | undefined;
    if (prefersReducedMotion() || graph.order < 3) {
      const iterations = graph.order < 300 ? 300 : graph.order < 1000 ? 150 : 80;
      if (graph.order > 1) forceAtlas2.assign(graph, { iterations, settings });
      sigma.refresh();
      setLayout('settled');
    } else {
      worker = new FA2Layout(graph, { settings });
      worker.start();
      setLayout('running');
      timer = window.setTimeout(() => {
        worker?.stop();
        setLayout('settled');
      }, Math.min(4000, 1200 + graph.order * 4));
    }

    return () => {
      window.clearTimeout(timer);
      worker?.kill();
      sigma.kill();
      sigmaRef.current = null;
    };
  }, [model]);

  // Keep keyboard focus on a node that is still on the map.
  useEffect(() => {
    setActive(a => (a && model.byId.has(a) ? a : null));
  }, [model]);

  // Restyle without rebuilding: selection, keyboard focus, theme.
  useEffect(() => {
    const neighbourhood = selected ? new Set([selected, ...(model.neighbours.get(selected) ?? [])]) : null;
    styling.current = {
      selected,
      active,
      highlight: neighbourhood,
      groups: gc.groups,
      other: gc.other,
      edge: gc.edge,
      edgeStrong: gc.edgeStrong,
      text: c.textPrimary,
      surface: c.surface,
    };
    // A full refresh: reducers only run when sigma re-indexes.
    sigmaRef.current?.refresh();
  }, [selected, active, model, gc, c.textPrimary, c.surface]);

  // The focus ring follows its node through layout, zoom and pan.
  const placeRing = useCallback(() => {
    const sigma = sigmaRef.current;
    if (!sigma || !active || !sigma.getGraph().hasNode(active)) {
      setRing(null);
      return;
    }
    const attrs = sigma.getGraph().getNodeAttributes(active);
    const p = sigma.graphToViewport({ x: attrs.x, y: attrs.y });
    const data = sigma.getNodeDisplayData(active);
    const r = sigma.scaleSize(data?.size ?? attrs.size) + 5;
    setRing(prev => (prev && Math.abs(prev.x - p.x) < 0.5 && Math.abs(prev.y - p.y) < 0.5 && prev.r === r ? prev : { x: p.x, y: p.y, r }));
  }, [active]);

  useEffect(() => {
    const sigma = sigmaRef.current;
    if (!sigma) return;
    placeRing();
    sigma.on('afterRender', placeRing);
    return () => {
      sigma.off('afterRender', placeRing);
    };
  }, [placeRing, model]);

  const animation = () => ({ duration: prefersReducedMotion() ? 0 : 250 });

  const viewportPositions = () => {
    const sigma = sigmaRef.current!;
    const graph = sigma.getGraph();
    return graph.mapNodes((id, attrs) => ({ id, ...sigma.graphToViewport({ x: attrs.x, y: attrs.y }) }));
  };

  /** Bring a node into view if keyboard focus moved it off screen. */
  const reveal = (id: string) => {
    const sigma = sigmaRef.current;
    if (!sigma) return;
    const { width, height: h } = sigma.getDimensions();
    const attrs = sigma.getGraph().getNodeAttributes(id);
    const p = sigma.graphToViewport({ x: attrs.x, y: attrs.y });
    const margin = 40;
    if (p.x < margin || p.y < margin || p.x > width - margin || p.y > h - margin) {
      const d = sigma.getNodeDisplayData(id);
      if (d) sigma.getCamera().animate({ x: d.x, y: d.y }, animation());
    }
  };

  const moveTo = (id: string) => {
    setActive(id);
    reveal(id);
    setAnnouncement(describeNode(modelRef.current, id));
  };

  const zoomIn = () => sigmaRef.current?.getCamera().zoomIn(animation());
  const zoomOut = () => sigmaRef.current?.getCamera().zoomOut(animation());
  const resetView = () => sigmaRef.current?.getCamera().reset(animation());
  const pan = (direction: Direction) => {
    const camera = sigmaRef.current?.getCamera();
    if (!camera) return;
    const step = PAN_STEP * camera.ratio;
    const delta = { up: [0, step], down: [0, -step], left: [-step, 0], right: [step, 0] }[direction];
    camera.animate({ x: camera.x + delta[0], y: camera.y + delta[1] }, animation());
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    const m = modelRef.current;
    const direction = ARROWS[e.key];
    if (direction && e.shiftKey) {
      e.preventDefault();
      pan(direction);
      return;
    }
    if (direction) {
      e.preventDefault();
      if (!active) {
        const start = startNode(m);
        if (start) moveTo(start);
        return;
      }
      const all = viewportPositions();
      const from = all.find(p => p.id === active);
      if (!from) return;
      const next = nodeInDirection(from, direction, all, m.neighbours.get(active) ?? new Set());
      if (next) moveTo(next);
      else setAnnouncement(`Nothing further ${direction === 'up' || direction === 'down' ? direction : `to the ${direction}`}.`);
      return;
    }
    switch (e.key) {
      case 'Enter':
      case ' ':
        if (active) {
          e.preventDefault();
          onSelect(active);
          setAnnouncement(`${describeNode(m, active)} Details are open after the map.`);
        }
        return;
      case 'Escape':
        if (selected) {
          e.preventDefault();
          onSelect(null);
          setAnnouncement('Details closed.');
        }
        return;
      case 'Home': {
        const start = startNode(m);
        if (start) {
          e.preventDefault();
          moveTo(start);
        }
        return;
      }
      case '+':
      case '=':
        e.preventDefault();
        zoomIn();
        return;
      case '-':
      case '_':
        e.preventDefault();
        zoomOut();
        return;
      case '0':
        e.preventDefault();
        resetView();
        return;
    }
  };

  const onFocus = () => {
    setHasFocus(true);
    const m = modelRef.current;
    const id = active && m.byId.has(active) ? active : startNode(m);
    if (id) {
      setActive(id);
      setAnnouncement(describeNode(m, id));
    }
  };

  const controlButton = (label: string, glyph: string, onClick: () => void) => (
    <Button
      key={label}
      variant="secondary"
      size="sm"
      aria-label={label}
      title={label}
      onClick={onClick}
      tabIndex={0}
    >
      <span aria-hidden="true">{glyph}</span>
    </Button>
  );

  return (
    <div>
      <div style={{ position: 'relative' }}>
        <div
          role="application"
          aria-roledescription="map"
          aria-label={ariaLabel}
          aria-describedby={[summaryId, hintId].filter(Boolean).join(' ')}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onFocus={onFocus}
          onBlur={() => setHasFocus(false)}
          data-graph-canvas=""
          data-layout={layout}
          data-node-count={model.nodes.length}
          data-active-node={active ?? ''}
          style={{
            position: 'relative',
            height,
            borderRadius: radius.md,
            border: `1px solid ${c.border}`,
            background: c.surface,
            overflow: 'hidden',
            outline: 'none',
            boxShadow: hasFocus ? `0 0 0 2px ${c.focus}` : 'none',
          }}
        >
          <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
          {hasFocus && ring && (
            <div
              aria-hidden="true"
              data-focus-ring=""
              style={{
                position: 'absolute',
                left: ring.x - ring.r,
                top: ring.y - ring.r,
                width: ring.r * 2,
                height: ring.r * 2,
                borderRadius: '50%',
                border: `2px solid ${c.focus}`,
                boxShadow: `0 0 0 2px ${c.surface}`,
                pointerEvents: 'none',
              }}
            />
          )}
        </div>
        <div
          role="group"
          aria-label="Map view controls"
          style={{
            position: 'absolute',
            top: space['2'],
            right: space['2'],
            display: 'grid',
            gridTemplateColumns: 'repeat(3, auto)',
            gap: space['1'],
          }}
        >
          {controlButton('Zoom in', '+', zoomIn)}
          {controlButton('Pan up', '↑', () => pan('up'))}
          {controlButton('Zoom out', '−', zoomOut)}
          {controlButton('Pan left', '←', () => pan('left'))}
          {controlButton('Reset view', '⟲', resetView)}
          {controlButton('Pan right', '→', () => pan('right'))}
          <span />
          {controlButton('Pan down', '↓', () => pan('down'))}
          <span />
        </div>
      </div>
      <p
        id={hintId}
        style={{ margin: `${space['2']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}
      >
        Keyboard: arrow keys move between nodes, Enter opens one, Escape closes it, + and − zoom, 0 resets,
        Shift with an arrow pans. Double-click a node to centre the map on it.
        {layout === 'running' ? ' Arranging the map…' : ''}
      </p>
      <div aria-live="polite" style={visuallyHidden} data-graph-announcer="">
        {announcement}
      </div>
    </div>
  );
}
