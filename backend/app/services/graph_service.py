"""The library graph (E-8.9 / S-8.9.1; plan: docs/plans/m9-citation-graph.md).

Nodes are the reader's visible documents (D-063 / D-070), the channels and
knowledge topics derived from them, and the reader's own job and library
answers that cite them. Edges:

* ``published_by`` document → channel (``documents.channel_id``)
* ``about``        document → topic (``extracted_knowledge_json.topics``)
* ``cites``        exchange → document (stored references)
* ``co_occurs``    topic ↔ topic, derived: topics sharing at least
  ``CO_OCCURRENCE_FLOOR`` documents, strongest few per topic

Everything is built from the visible set, so another reader's documents,
answers, channels or topics can never appear, and an empty visible set is
an empty graph. Computed per request: the plan sizes a tenant at under
5,000 nodes, where this is milliseconds; a persisted edge table waits until
it is measured to be slow.

Under the cap, nodes are chosen by degree, then recency; with ``focus``,
the graph is the focus node's neighbourhood to ``depth`` hops (the
"local graph" the plan makes the default view).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.services import shelf_service, visibility_service
from app.services.channel_intelligence_service import display_label

DEFAULT_LIMIT = 300
MAX_LIMIT = 2_000
MAX_DEPTH = 3
TOPIC_FLOOR = 2  # a topic must label at least this many visible documents
TOPICS_PER_DOCUMENT = 8
CO_OCCURRENCE_FLOOR = 2
CO_OCCURRENCE_PER_TOPIC = 5
MAX_EXCHANGES = 2_000
NODE_TYPES = ("document", "channel", "topic", "exchange")


class GraphScopeNotFound(Exception):
    """A shelf or job filter that is not the caller's."""


@dataclass
class _Graph:
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: dict[tuple[str, str, str], int] = field(default_factory=dict)
    recency: dict[str, float] = field(default_factory=dict)

    def node(self, node_id: str, type_: str, label: str, meta: dict | None = None, when: datetime | None = None):
        if node_id not in self.nodes:
            self.nodes[node_id] = {"id": node_id, "type": type_, "label": label, "meta": meta or {}}
            self.recency[node_id] = when.timestamp() if when else 0.0

    def edge(self, a: str, b: str, type_: str, weight: int = 1):
        key = (a, b, type_)
        self.edges[key] = self.edges.get(key, 0) + weight

    def adjacency(self) -> dict[str, set[str]]:
        adj: dict[str, set[str]] = defaultdict(set)
        for a, b, _ in self.edges:
            adj[a].add(b)
            adj[b].add(a)
        return adj


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _scoped_documents(
    db: Session,
    tenant_id: str,
    *,
    shelf_id: str | None,
    channel_id: str | None,
    job_id: str | None,
) -> list[Document]:
    q = db.query(Document).filter(
        Document.document_id.in_(visibility_service.visible_document_ids(db, tenant_id))
    )
    if shelf_id:
        shelf = shelf_service.get_shelf(db, shelf_id, tenant_id)
        if shelf is None:
            raise GraphScopeNotFound("shelf")
        job_ids = shelf_service.job_ids_for_shelf(db, shelf.id)
        if not job_ids:
            return []
        q = q.filter(
            Document.document_id.in_(
                db.query(JobVideo.document_id).filter(JobVideo.job_id.in_(job_ids))
            )
        )
    if job_id:
        job = db.query(Job).filter(Job.id == job_id, Job.tenant_id == tenant_id).first()
        if job is None:
            raise GraphScopeNotFound("job")
        q = q.filter(
            Document.document_id.in_(
                db.query(JobVideo.document_id).filter(JobVideo.job_id == job.id)
            )
        )
    if channel_id:
        q = q.filter(Document.channel_id == channel_id)
    return q.all()


def _topics(doc: Document) -> list[str]:
    if not doc.extracted_knowledge_json:
        return []
    try:
        data = json.loads(doc.extracted_knowledge_json)
    except (TypeError, ValueError):
        return []
    out: list[str] = []
    for raw in (data.get("topics") or []) if isinstance(data, dict) else []:
        if isinstance(raw, dict):
            raw = raw.get("name") or raw.get("label") or ""
        label = " ".join(str(raw or "").split()).strip(" .;:,")
        if len(label) >= 2 and label.lower() not in {t.lower() for t in out}:
            out.append(label)
        if len(out) >= TOPICS_PER_DOCUMENT:
            break
    return out


def _video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return None
    host = (parsed.netloc or "").lower()
    if host.endswith("youtu.be"):
        return parsed.path.strip("/").split("/")[0] or None
    if "youtube" in host:
        values = parse_qs(parsed.query).get("v")
        return values[0] if values else None
    return None


def _cited_documents(refs_json: str | None, by_video: dict[str, str], by_url: dict[str, str]) -> set[str]:
    try:
        refs = json.loads(refs_json or "[]")
    except (TypeError, ValueError):
        return set()
    out: set[str] = set()
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, dict):
            continue
        vid = ref.get("video_id") or _video_id(ref.get("youtube_link") or "") or _video_id(ref.get("video_url") or "")
        if vid and vid in by_video:
            out.add(by_video[vid])
            continue
        for key in ("permalink", "video_url", "source_url"):
            url = (ref.get(key) or "").split("#")[0]
            if url and url in by_url:
                out.add(by_url[url])
                break
    return out


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _build(db: Session, tenant_id: str, docs: list[Document], types: set[str]) -> _Graph:
    g = _Graph()
    if not docs:
        return g

    channel_names = {}
    channel_ids = {d.channel_id for d in docs if d.channel_id}
    if channel_ids and "channel" in types:
        channel_names = {
            cid: name
            for cid, name in db.query(Channel.channel_id, Channel.name).filter(Channel.channel_id.in_(channel_ids))
        }

    topic_docs: dict[str, list[str]] = defaultdict(list)
    topic_label: dict[str, Counter] = defaultdict(Counter)
    for d in docs:
        node_id = f"document:{d.document_id}"
        g.node(
            node_id,
            "document",
            d.title or "Untitled",
            {
                "document_id": d.document_id,
                "url": d.url,
                "source_type": d.source_type or "video",
                "channel_id": d.channel_id,
                "published_at": d.published_at.isoformat() if d.published_at else None,
            },
            when=d.published_at or d.created_at,
        )
        if "channel" in types and d.channel_id and d.channel_id in channel_names:
            cid = f"channel:{d.channel_id}"
            g.node(cid, "channel", channel_names[d.channel_id] or d.channel_id, {"channel_id": d.channel_id})
            g.edge(node_id, cid, "published_by")
        if "topic" in types:
            for label in _topics(d):
                key = label.lower()
                topic_docs[key].append(node_id)
                topic_label[key][label] += 1

    if "topic" in types:
        kept_topics = {k: ds for k, ds in topic_docs.items() if len(ds) >= TOPIC_FLOOR}
        for key, doc_ids in kept_topics.items():
            tid = f"topic:{key}"
            g.node(tid, "topic", display_label(topic_label[key]), {"documents": len(doc_ids)})
            for doc_node in doc_ids:
                g.edge(doc_node, tid, "about")
        # Derived topic ↔ topic co-occurrence, strongest few per topic.
        doc_topics: dict[str, list[str]] = defaultdict(list)
        for key, doc_ids in kept_topics.items():
            for doc_node in doc_ids:
                doc_topics[doc_node].append(key)
        pair_counts: Counter = Counter()
        for keys in doc_topics.values():
            keys = sorted(keys)
            for i in range(len(keys)):
                for j in range(i + 1, len(keys)):
                    pair_counts[(keys[i], keys[j])] += 1
        per_topic: dict[str, int] = Counter()
        for (a, b), n in pair_counts.most_common():
            if n < CO_OCCURRENCE_FLOOR:
                break
            if per_topic[a] >= CO_OCCURRENCE_PER_TOPIC or per_topic[b] >= CO_OCCURRENCE_PER_TOPIC:
                continue
            g.edge(f"topic:{a}", f"topic:{b}", "co_occurs", n)
            per_topic[a] += 1
            per_topic[b] += 1

    if "exchange" in types:
        by_video = {d.video_id: f"document:{d.document_id}" for d in docs if d.video_id}
        by_url = {d.url: f"document:{d.document_id}" for d in docs if d.url}
        rows = [
            ("job", ex.id, ex.question, ex.created_at, ex.job_id, ex.references)
            for ex in db.query(QAExchange)
            .filter(QAExchange.tenant_id == tenant_id)
            .order_by(QAExchange.created_at.desc())
            .limit(MAX_EXCHANGES)
        ] + [
            ("library", ex.id, ex.question, ex.created_at, None, ex.references_json)
            for ex in db.query(LibraryQAExchange)
            .filter(LibraryQAExchange.tenant_id == tenant_id)
            .order_by(LibraryQAExchange.created_at.desc())
            .limit(MAX_EXCHANGES)
        ]
        for kind, ex_id, question, created_at, job_id, refs in rows:
            cited = _cited_documents(refs, by_video, by_url)
            if not cited:
                continue
            eid = f"exchange:{kind}:{ex_id}"
            g.node(
                eid,
                "exchange",
                question,
                {"kind": kind, "exchange_id": ex_id, "job_id": job_id},
                when=created_at,
            )
            for doc_node in cited:
                g.edge(eid, doc_node, "cites")
    return g


def _components(node_ids: set[str], edges: list[tuple[str, str]]) -> list[set[str]]:
    parent = {n: n for n in node_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups: dict[str, set[str]] = defaultdict(set)
    for n in node_ids:
        groups[find(n)].add(n)
    return sorted(groups.values(), key=len, reverse=True)


def _counts(nodes) -> dict:
    c = Counter(n["type"] for n in nodes)
    return {"documents": c["document"], "channels": c["channel"], "topics": c["topic"], "exchanges": c["exchange"]}


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _summary(g: _Graph, kept: list[dict], kept_edges: list[tuple[str, str]], total_nodes: int, focus: str | None) -> str:
    if total_nodes == 0:
        return "Your library has nothing to draw yet: no documents you can see match this view."
    counts = _counts(kept)
    parts = [
        _plural(counts["documents"], "document", "documents"),
        _plural(counts["topics"], "topic", "topics"),
        _plural(counts["channels"], "channel", "channels"),
        _plural(counts["exchanges"], "of your answers", "of your answers"),
    ]
    text = "Showing " + ", ".join(parts[:-1]) + " and " + parts[-1]
    if focus and focus in g.nodes:
        text += f", around “{g.nodes[focus]['label']}”"
    text += "."
    if len(kept) < total_nodes:
        text += f" {len(kept)} of {total_nodes} nodes are shown, the most connected first."
    groups = _components({n["id"] for n in kept}, kept_edges)
    if groups:
        biggest = groups[0]
        topics_in = [g.nodes[n] for n in biggest if g.nodes[n]["type"] == "topic"]
        topics_in.sort(key=lambda n: -n["degree"])
        text += f" They form {_plural(len(groups), 'connected group', 'connected groups')}; the largest holds {len(biggest)} nodes"
        if topics_in:
            text += ", mostly about " + ", ".join(t["label"] for t in topics_in[:3])
        text += "."
    return text


def build_graph(
    db: Session,
    tenant_id: str,
    *,
    focus: str | None = None,
    depth: int = 1,
    shelf_id: str | None = None,
    channel_id: str | None = None,
    job_id: str | None = None,
    types: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    wanted = {t for t in (types or NODE_TYPES) if t in NODE_TYPES} | {"document"}
    limit = max(1, min(limit, MAX_LIMIT))
    depth = max(1, min(depth, MAX_DEPTH))

    docs = _scoped_documents(db, tenant_id, shelf_id=shelf_id, channel_id=channel_id, job_id=job_id)
    g = _build(db, tenant_id, docs, wanted)

    adj = g.adjacency()
    for node in g.nodes.values():
        node["degree"] = len(adj.get(node["id"], ()))

    candidates = list(g.nodes)
    focus_found = focus if focus in g.nodes else None
    if focus_found:
        seen = {focus_found: 0}
        queue = deque([focus_found])
        while queue:
            current = queue.popleft()
            if seen[current] >= depth:
                continue
            for nxt in adj.get(current, ()):
                if nxt not in seen:
                    seen[nxt] = seen[current] + 1
                    queue.append(nxt)
        candidates = list(seen)

    def rank(node_id: str):
        # The focus first, then by degree, then the most recent.
        return (node_id != focus_found, -g.nodes[node_id]["degree"], -g.recency.get(node_id, 0.0), node_id)

    chosen = sorted(candidates, key=rank)[:limit]
    chosen_set = set(chosen)
    kept_nodes = [g.nodes[n] for n in chosen]
    kept_edge_list = [
        {"source": a, "target": b, "type": t, "weight": w}
        for (a, b, t), w in g.edges.items()
        if a in chosen_set and b in chosen_set
    ]
    summary = _summary(
        g, kept_nodes, [(e["source"], e["target"]) for e in kept_edge_list], len(g.nodes), focus_found
    )
    return {
        "nodes": kept_nodes,
        "edges": kept_edge_list,
        "truncated": len(chosen) < len(g.nodes),
        "total": _counts(g.nodes.values()),
        "shown": _counts(kept_nodes),
        "summary": summary,
        "focus": focus_found,
    }
