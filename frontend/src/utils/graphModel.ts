/**
 * The library map's data model (S-8.9.2), kept pure so the canvas and the
 * table view are provably built from the same node set (M9 plan, test
 * strategy). Takes `GET /library/graph` and returns the nodes to draw, their
 * groups (Louvain communities), seeded starting positions and sizes, plus the
 * helpers the keyboard model needs.
 */
import Graph from 'graphology';
import louvain from 'graphology-communities-louvain';
import type { GraphEdge, GraphNode, GraphNodeType, GraphResponse } from '../services/graphApi';

/** A glyph in front of every non-source label, so a node's kind never rests
 * on colour or size alone (WCAG 1.4.1). */
export const TYPE_GLYPH: Record<GraphNodeType, string> = {
  document: '',
  channel: '▸',
  topic: '#',
  exchange: '?',
};

export const TYPE_NAME: Record<GraphNodeType, string> = {
  document: 'Source',
  channel: 'Channel',
  topic: 'Topic',
  exchange: 'Your question',
};

export const EDGE_NAME: Record<GraphEdge['type'], string> = {
  published_by: 'published by',
  about: 'is about',
  cites: 'cites',
  co_occurs: 'appears with',
};

/** Only this many groups get a colour: a fourth categorical hue fails the
 * all-pairs separation checks a node-link map needs (see `groupColors`). */
export const MAX_COLOURED_GROUPS = 3;

export interface ModelNode extends GraphNode {
  /** Edges to other nodes on this map (the API `degree` counts the whole library). */
  shownDegree: number;
  /** Index into `GraphModel.groups`. */
  group: number;
  x: number;
  y: number;
  size: number;
  /** The label with its type glyph. */
  displayLabel: string;
}

export interface ModelGroup {
  index: number;
  name: string;
  size: number;
  /** Colour slot, or null for a group drawn as "other". */
  slot: number | null;
  /** The group's most connected topics (or nodes, when it has no topic). */
  about: string[];
}

export interface GraphModel {
  nodes: ModelNode[];
  edges: GraphEdge[];
  groups: ModelGroup[];
  /** Single-link nodes left off the global map. */
  hiddenLeaves: number;
  focus: string | null;
  byId: Map<string, ModelNode>;
  neighbours: Map<string, Set<string>>;
}

export interface ModelOptions {
  /** Leave single-link nodes off the global map (the default); a local
   * view around a node never hides them, or it would be nearly empty. */
  hideLeaves: boolean;
}

/** FNV-1a: a stable hash so the same library always starts from the same layout. */
export function hashString(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** mulberry32: a seeded generator, so Louvain gives the same groups each time. */
export function seededRandom(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function nodeSize(shownDegree: number): number {
  return 4 + Math.min(10, 2 * Math.sqrt(shownDegree));
}

function payloadDegrees(nodes: GraphNode[], edges: GraphEdge[]): Map<string, number> {
  const ids = new Set(nodes.map(n => n.id));
  const deg = new Map<string, number>(nodes.map(n => [n.id, 0]));
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target) || e.source === e.target) continue;
    deg.set(e.source, (deg.get(e.source) ?? 0) + 1);
    deg.set(e.target, (deg.get(e.target) ?? 0) + 1);
  }
  return deg;
}

export function buildModel(
  resp: Pick<GraphResponse, 'nodes' | 'edges' | 'focus'>,
  opts: ModelOptions,
): GraphModel {
  const focus = resp.focus ?? null;
  const deg = payloadDegrees(resp.nodes, resp.edges);
  const hide = opts.hideLeaves && !focus;
  const kept = resp.nodes.filter(n => !hide || n.id === focus || (deg.get(n.id) ?? 0) > 1);
  const keptIds = new Set(kept.map(n => n.id));
  const edges = resp.edges.filter(
    e => e.source !== e.target && keptIds.has(e.source) && keptIds.has(e.target),
  );

  const neighbours = new Map<string, Set<string>>(kept.map(n => [n.id, new Set<string>()]));
  const g = new Graph({ type: 'undirected', multi: false });
  for (const n of kept) g.addNode(n.id);
  for (const e of edges) {
    neighbours.get(e.source)!.add(e.target);
    neighbours.get(e.target)!.add(e.source);
    if (g.hasEdge(e.source, e.target)) {
      g.updateEdgeAttribute(e.source, e.target, 'weight', w => (w ?? 0) + e.weight);
    } else {
      g.addEdge(e.source, e.target, { weight: e.weight });
    }
  }

  // Groups: Louvain communities, seeded, then ordered by size (ties by the
  // smallest member id) so the numbering is stable for the same map.
  const raw: Record<string, number> =
    g.size > 0
      ? louvain(g, { getEdgeWeight: 'weight', rng: seededRandom(42) })
      : Object.fromEntries(kept.map((n, i) => [n.id, i]));
  const members = new Map<number, string[]>();
  for (const n of kept) {
    const c = raw[n.id];
    if (!members.has(c)) members.set(c, []);
    members.get(c)!.push(n.id);
  }
  const ordered = [...members.values()]
    .map(ids => ids.sort())
    .sort((a, b) => b.length - a.length || (a[0] < b[0] ? -1 : 1));
  const groupOf = new Map<string, number>();
  ordered.forEach((ids, i) => ids.forEach(id => groupOf.set(id, i)));

  const shownDegree = (id: string) => neighbours.get(id)?.size ?? 0;
  const byLabel = new Map(kept.map(n => [n.id, n]));
  const groups: ModelGroup[] = ordered.map((ids, i) => {
    const byDegree = [...ids].sort((a, b) => shownDegree(b) - shownDegree(a) || (a < b ? -1 : 1));
    const topics = byDegree.filter(id => byLabel.get(id)!.type === 'topic');
    const about = (topics.length ? topics : byDegree).slice(0, 3).map(id => byLabel.get(id)!.label);
    return {
      index: i,
      name: `Group ${i + 1}`,
      size: ids.length,
      slot: i < MAX_COLOURED_GROUPS && ids.length > 1 ? i : null,
      about,
    };
  });

  // Seeded start: groups spread round a circle, members jittered round their
  // group's centre. ForceAtlas2 takes it from there.
  const ring = Math.max(1, groups.length);
  const nodes: ModelNode[] = kept.map(n => {
    const group = groupOf.get(n.id) ?? 0;
    const angle = (2 * Math.PI * group) / ring;
    const spread = groups.length > 1 ? 10 : 0;
    const h = hashString(n.id);
    const r = seededRandom(h);
    const sd = shownDegree(n.id);
    return {
      ...n,
      shownDegree: sd,
      group,
      x: spread * Math.cos(angle) + (r() - 0.5) * 6,
      y: spread * Math.sin(angle) + (r() - 0.5) * 6,
      size: nodeSize(sd),
      displayLabel: TYPE_GLYPH[n.type] ? `${TYPE_GLYPH[n.type]} ${n.label}` : n.label,
    };
  });

  return {
    nodes,
    edges,
    groups,
    hiddenLeaves: resp.nodes.length - kept.length,
    focus: focus && keptIds.has(focus) ? focus : null,
    byId: new Map(nodes.map(n => [n.id, n])),
    neighbours,
  };
}

/** Where keyboard focus lands when the map takes focus: the focus node,
 * otherwise the most connected node (ties by id). */
export function startNode(model: GraphModel): string | null {
  if (model.focus) return model.focus;
  let best: ModelNode | null = null;
  for (const n of model.nodes) {
    if (!best || n.shownDegree > best.shownDegree || (n.shownDegree === best.shownDegree && n.id < best.id)) best = n;
  }
  return best?.id ?? null;
}

export type Direction = 'up' | 'down' | 'left' | 'right';

const VECTORS: Record<Direction, [number, number]> = {
  up: [0, -1],
  down: [0, 1],
  left: [-1, 0],
  right: [1, 0],
};

/**
 * The node an arrow key moves to: the nearest in that direction on screen
 * (within 60° of it), preferring the current node's neighbours and falling
 * back to any node, so every part of the map is reachable by keyboard.
 * Coordinates are viewport pixels (y grows downward).
 */
export function nodeInDirection(
  from: { x: number; y: number },
  direction: Direction,
  candidates: { id: string; x: number; y: number }[],
  preferred: Set<string>,
): string | null {
  const [dx, dy] = VECTORS[direction];
  let bestPreferred: { id: string; score: number } | null = null;
  let bestAny: { id: string; score: number } | null = null;
  for (const c of candidates) {
    const vx = c.x - from.x;
    const vy = c.y - from.y;
    const dist = Math.hypot(vx, vy);
    if (dist < 0.5) continue;
    const cos = (vx * dx + vy * dy) / dist;
    if (cos < 0.5) continue;
    const score = dist * (2 - cos);
    if (!bestAny || score < bestAny.score) bestAny = { id: c.id, score };
    if (preferred.has(c.id) && (!bestPreferred || score < bestPreferred.score)) bestPreferred = { id: c.id, score };
  }
  return bestPreferred?.id ?? bestAny?.id ?? null;
}

/** What the live region says when keyboard focus lands on a node. */
export function describeNode(model: GraphModel, id: string): string {
  const n = model.byId.get(id);
  if (!n) return '';
  const g = model.groups[n.group];
  const links = n.shownDegree === 1 ? '1 connection' : `${n.shownDegree} connections`;
  return `${TYPE_NAME[n.type]}: ${n.label}. ${links}. ${g ? g.name : ''}.`;
}

/** A node's neighbours on the map, most connected first. */
export function neighbourNodes(model: GraphModel, id: string): ModelNode[] {
  return [...(model.neighbours.get(id) ?? [])]
    .map(nid => model.byId.get(nid)!)
    .sort((a, b) => b.shownDegree - a.shownDegree || (a.label < b.label ? -1 : a.label > b.label ? 1 : a.id < b.id ? -1 : 1));
}

export function neighbourLabels(model: GraphModel, id: string): string[] {
  return neighbourNodes(model, id).map(n => n.displayLabel);
}

/** The table view's rows: exactly the nodes on the map, most connected first. */
export function tableNodes(model: GraphModel): ModelNode[] {
  return [...model.nodes].sort(
    (a, b) => b.shownDegree - a.shownDegree || a.group - b.group || (a.label < b.label ? -1 : 1),
  );
}
