import { describe, expect, it } from 'vitest';
import type { GraphEdge, GraphNode, GraphResponse } from '../../services/graphApi';
import {
  MAX_COLOURED_GROUPS,
  buildModel,
  describeNode,
  nodeInDirection,
  startNode,
  tableNodes,
} from '../graphModel';

function node(id: string, type: GraphNode['type'] = 'document', label = id): GraphNode {
  return { id, type, label, degree: 0, meta: {} };
}

function edge(source: string, target: string, type: GraphEdge['type'] = 'about', weight = 1): GraphEdge {
  return { source, target, type, weight };
}

/** Two dense clusters joined by one bridge, a pendant leaf and an isolated node. */
function sample(focus: string | null = null): Pick<GraphResponse, 'nodes' | 'edges' | 'focus'> {
  const nodes = [
    node('document:a1'), node('document:a2'), node('document:a3'), node('topic:alpha', 'topic', 'Alpha'),
    node('document:b1'), node('document:b2'), node('document:b3'), node('topic:beta', 'topic', 'Beta'),
    node('channel:c', 'channel', 'Chan'),
    node('exchange:library:q', 'exchange', 'Why?'),
    node('document:alone'),
  ];
  const edges = [
    edge('document:a1', 'topic:alpha'), edge('document:a2', 'topic:alpha'), edge('document:a3', 'topic:alpha'),
    edge('document:a1', 'document:a2', 'cites'), edge('document:a2', 'document:a3', 'cites'),
    edge('document:b1', 'topic:beta'), edge('document:b2', 'topic:beta'), edge('document:b3', 'topic:beta'),
    edge('document:b1', 'document:b2', 'cites'), edge('document:b2', 'document:b3', 'cites'),
    edge('topic:alpha', 'topic:beta', 'co_occurs'),
    edge('document:a1', 'channel:c', 'published_by'),
    edge('exchange:library:q', 'document:b1', 'cites'),
  ];
  return { nodes, edges, focus };
}

describe('buildModel', () => {
  it('hides single-link nodes on the global map and drops their edges', () => {
    const m = buildModel(sample(), { hideLeaves: true });
    const ids = m.nodes.map(n => n.id);
    expect(ids).not.toContain('channel:c');
    expect(ids).not.toContain('exchange:library:q');
    expect(ids).not.toContain('document:alone');
    expect(m.hiddenLeaves).toBe(3);
    const kept = new Set(ids);
    expect(m.edges.every(e => kept.has(e.source) && kept.has(e.target))).toBe(true);
  });

  it('keeps every node when leaves are shown, and never hides them around a focus', () => {
    expect(buildModel(sample(), { hideLeaves: false }).nodes).toHaveLength(11);
    const local = buildModel(sample('document:a1'), { hideLeaves: true });
    expect(local.nodes).toHaveLength(11);
    expect(local.hiddenLeaves).toBe(0);
    expect(local.focus).toBe('document:a1');
  });

  it('finds the two clusters as groups, largest first, deterministically', () => {
    const one = buildModel(sample(), { hideLeaves: true });
    const two = buildModel(sample(), { hideLeaves: true });
    expect(one.groups.map(g => g.size)).toEqual([4, 4]);
    const groupOf = (id: string) => one.byId.get(id)!.group;
    expect(groupOf('document:a1')).toBe(groupOf('topic:alpha'));
    expect(groupOf('document:b3')).toBe(groupOf('topic:beta'));
    expect(groupOf('document:a1')).not.toBe(groupOf('document:b1'));
    expect(one.nodes.map(n => [n.id, n.group, n.x, n.y])).toEqual(two.nodes.map(n => [n.id, n.group, n.x, n.y]));
    expect(one.groups[0].about[0]).toMatch(/Alpha|Beta/);
  });

  it('colours at most three groups and never a group of one', () => {
    const nodes: GraphNode[] = [];
    const edges: GraphEdge[] = [];
    for (let c = 0; c < 5; c++) {
      for (let i = 0; i < 3; i++) nodes.push(node(`document:${c}-${i}`));
      edges.push(edge(`document:${c}-0`, `document:${c}-1`), edge(`document:${c}-1`, `document:${c}-2`), edge(`document:${c}-0`, `document:${c}-2`));
    }
    nodes.push(node('document:solo'));
    const m = buildModel({ nodes, edges, focus: null }, { hideLeaves: false });
    expect(m.groups).toHaveLength(6);
    expect(m.groups.filter(g => g.slot !== null)).toHaveLength(MAX_COLOURED_GROUPS);
    expect(m.groups.find(g => g.size === 1)!.slot).toBeNull();
  });

  it('marks a node kind with a glyph, not colour alone', () => {
    const m = buildModel(sample(), { hideLeaves: false });
    expect(m.byId.get('topic:alpha')!.displayLabel).toBe('# Alpha');
    expect(m.byId.get('channel:c')!.displayLabel).toBe('▸ Chan');
    expect(m.byId.get('exchange:library:q')!.displayLabel).toBe('? Why?');
    expect(m.byId.get('document:a1')!.displayLabel).toBe('document:a1');
  });

  it('copes with an empty graph and a graph with no edges', () => {
    const empty = buildModel({ nodes: [], edges: [], focus: null }, { hideLeaves: true });
    expect(empty.nodes).toEqual([]);
    expect(startNode(empty)).toBeNull();
    const flat = buildModel({ nodes: [node('document:x'), node('document:y')], edges: [], focus: null }, { hideLeaves: false });
    expect(flat.groups).toHaveLength(2);
    expect(flat.groups.every(g => g.slot === null)).toBe(true);
  });
});

describe('the table view', () => {
  it('lists exactly the nodes the map draws', () => {
    for (const hideLeaves of [true, false]) {
      const m = buildModel(sample(), { hideLeaves });
      expect(new Set(tableNodes(m).map(n => n.id))).toEqual(new Set(m.nodes.map(n => n.id)));
      expect(tableNodes(m)).toHaveLength(m.nodes.length);
    }
  });
});

describe('keyboard model', () => {
  it('starts on the focus node, else the most connected', () => {
    expect(startNode(buildModel(sample('channel:c'), { hideLeaves: true }))).toBe('channel:c');
    const m = buildModel(sample(), { hideLeaves: true });
    const top = Math.max(...m.nodes.map(n => n.shownDegree));
    expect(m.byId.get(startNode(m)!)!.shownDegree).toBe(top);
  });

  it('moves to the nearest node in the arrow direction, neighbours first', () => {
    const from = { x: 100, y: 100 };
    const candidates = [
      { id: 'near-right', x: 140, y: 100 },
      { id: 'far-right-neighbour', x: 220, y: 110 },
      { id: 'above', x: 100, y: 40 },
      { id: 'diagonal', x: 160, y: 160 },
    ];
    expect(nodeInDirection(from, 'right', candidates, new Set())).toBe('near-right');
    expect(nodeInDirection(from, 'right', candidates, new Set(['far-right-neighbour']))).toBe('far-right-neighbour');
    expect(nodeInDirection(from, 'up', candidates, new Set())).toBe('above');
    expect(nodeInDirection(from, 'left', candidates, new Set())).toBeNull();
    // 45° sits inside the 60° cone; it is still found when nothing is straighter.
    expect(nodeInDirection(from, 'down', candidates, new Set())).toBe('diagonal');
  });

  it('describes a node for the live region', () => {
    const m = buildModel(sample(), { hideLeaves: true });
    expect(describeNode(m, 'topic:alpha')).toMatch(/^Topic: Alpha\. 4 connections\. Group \d\.$/);
    expect(describeNode(m, 'nope')).toBe('');
  });
});
