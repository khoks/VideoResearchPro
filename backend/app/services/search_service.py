"""Global keyword search — the endpoint behind the command palette (S-8.2.1 / M2).

Plan: ``docs/plans/m2-command-palette.md``. Five entity groups — jobs,
documents, channels, Q&A exchanges, knowledge reports — searched by one
tenant-scoped endpoint, ``GET /api/v1/search``.

**Engine.** SQLite FTS5 when the linked SQLite has it (python.org, macOS and
uv builds do; Linux distro Pythons link the system library and may not), a
plain ``LIKE`` scan otherwise. The probe runs once per process in
``ensure_index`` and the result is reported on ``GET /health`` as
``search_backend`` so the UI can label the fallback.

**One trigram FTS5 table per entity** (``fts_documents``, ``fts_jobs``,
``fts_channels``, ``fts_qa``, ``fts_knowledge``), each ``(id UNINDEXED,
<text columns…>)``. The plan sketched a ``unicode61`` table plus a separate
trigram table per entity; the trigram tokenizer alone covers both the
word-prefix and the mid-word substring cases (case-insensitive, diacritics
folded on SQLite ≥ 3.45, Devanagari matched by codepoint trigrams), so the
second table bought nothing at this scale except more triggers. The cost is
index size, which is irrelevant for thousands of rows. Queries shorter than
three characters cannot match a trigram index and take the ``LIKE`` path
even when FTS5 is present.

**Not external-content tables.** FTS5's ``content=`` mode maps on rowid, and
every base table here has a string primary key, so its rowids are not
stable across ``VACUUM``. Each FTS row therefore carries the entity id as an
``UNINDEXED`` column and duplicates the indexed text (titles, questions,
and the knowledge Markdown — small, and the only one that is not tiny).
``AFTER INSERT / UPDATE OF <cols> / DELETE`` triggers keep them current;
``rebuild_index`` repopulates from the base tables whenever a table was
just created (first boot, or a Python upgrade that gained FTS5).

**Tenant scoping is applied to the FTS hit list by joining the entity's
tenant anchor**, never by a tenant column inside the FTS table:
``jobs.tenant_id``, ``document_visibility`` (D-063: a tenant with no grants
gets nothing, never everything), ``channel_subscriptions`` ∪ visible
documents' channels (D-065), and ``*_qa_exchanges.tenant_id``.

**Ranking.** ``bm25()`` with the title column weighted over the body,
recency as the tie-break, a per-group cap. The ``LIKE`` path has no score
(every item reports ``0.0``) and orders by recency alone.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import or_, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.channel_subscription import ChannelSubscription
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.models.qa_history_exchange import QAHistoryExchange

logger = logging.getLogger(__name__)

BACKEND_FTS5 = "fts5"
BACKEND_LIKE = "like"

# Every FTS table and its SQLite shadow tables (`fts_x_data`, `fts_x_idx`,
# `fts_x_content`, `fts_x_docsize`, `fts_x_config`) start with this prefix;
# schema_init_service ignores them when comparing the live DB to the ORM.
FTS_PREFIX = "fts_"

SEARCH_TYPES: tuple[str, ...] = ("jobs", "documents", "channels", "qa", "knowledge")

# A trigram index cannot match fewer than three characters.
MIN_MATCH_CHARS = 3

# Over-fetch factor for the FTS path so that ties at the bm25 boundary are
# broken by recency before the cut, not by the index's internal order.
_OVERFETCH = 4

# Set by ensure_index(); read by search() and /health. None = never probed
# (a process that never ran the lifespan, e.g. a bare script) → LIKE.
_backend: str | None = None
_tokenize: str | None = None


# ---------------------------------------------------------------------------
# Schema: one spec per FTS table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Source:
    """One base table feeding an FTS table. `columns` are (fts_col, sql_expr)
    pairs; `extra` are UNINDEXED literal columns (the Q&A surface)."""

    table: str
    id_col: str
    columns: tuple[tuple[str, str, str], ...]  # (fts column, base column, SQL template over %s)
    extra: tuple[tuple[str, str], ...] = ()
    only_when: str | None = None  # SQL predicate on `new.` for the insert trigger


@dataclass(frozen=True)
class _FtsSpec:
    name: str
    text_columns: tuple[str, ...]
    unindexed: tuple[str, ...]
    weights: tuple[float, ...]
    sources: tuple[_Source, ...]


_SPECS: dict[str, _FtsSpec] = {
    "documents": _FtsSpec(
        name="fts_documents",
        text_columns=("title", "description"),
        unindexed=(),
        weights=(5.0, 1.0),
        sources=(
            _Source(
                table="documents",
                id_col="document_id",
                columns=(("title", "title", "coalesce(%s.title, '')"), ("description", "description", "coalesce(%s.description, '')")),
            ),
        ),
    ),
    "jobs": _FtsSpec(
        name="fts_jobs",
        text_columns=("topic", "instructions"),
        unindexed=(),
        weights=(5.0, 1.0),
        sources=(
            _Source(
                table="jobs",
                id_col="id",
                columns=(("topic", "topic", "coalesce(%s.topic, '')"), ("instructions", "search_instructions", "coalesce(%s.search_instructions, '')")),
            ),
        ),
    ),
    "channels": _FtsSpec(
        name="fts_channels",
        text_columns=("name",),
        unindexed=(),
        weights=(1.0,),
        sources=(
            _Source(table="channels", id_col="channel_id", columns=(("name", "name", "coalesce(%s.name, '')"),)),
        ),
    ),
    "qa": _FtsSpec(
        name="fts_qa",
        text_columns=("question",),
        unindexed=("surface",),
        weights=(1.0,),
        sources=(
            _Source(table="qa_exchanges", id_col="id", columns=(("question", "question", "coalesce(%s.question, '')"),), extra=(("surface", "'job'"),)),
            _Source(table="library_qa_exchanges", id_col="id", columns=(("question", "question", "coalesce(%s.question, '')"),), extra=(("surface", "'library'"),)),
            _Source(table="qa_history_exchanges", id_col="id", columns=(("question", "question", "coalesce(%s.question, '')"),), extra=(("surface", "'history'"),)),
        ),
    ),
    "knowledge": _FtsSpec(
        name="fts_knowledge",
        text_columns=("body",),
        unindexed=(),
        weights=(1.0,),
        sources=(
            _Source(
                table="documents",
                id_col="document_id",
                columns=(("body", "knowledge_report_md", "%s.knowledge_report_md"),),
                only_when="%s.knowledge_report_md IS NOT NULL",
            ),
        ),
    ),
}


def fts_table_names() -> list[str]:
    return [spec.name for spec in _SPECS.values()]


def _create_table_sql(spec: _FtsSpec, tokenize: str) -> str:
    cols = ["id UNINDEXED", *(f"{c} UNINDEXED" for c in spec.unindexed), *spec.text_columns]
    return (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {spec.name} USING fts5("
        f"{', '.join(cols)}, tokenize='{tokenize}')"
    )


def _insert_select(spec: _FtsSpec, src: _Source, alias: str) -> tuple[str, str]:
    """Return (column list, value list) for inserting one `src` row into the
    FTS table, with `alias` standing for the source row (`new` in a trigger,
    the table alias in a rebuild)."""
    names = ["id", *(n for n, _ in src.extra), *(n for n, _, _ in src.columns)]
    values = [f"{alias}.{src.id_col}", *(v for _, v in src.extra), *(tpl % alias for _, _, tpl in src.columns)]
    return ", ".join(names), ", ".join(values)


def _trigger_sql(spec: _FtsSpec, src: _Source) -> list[str]:
    cols, vals = _insert_select(spec, src, "new")
    when = f" WHEN {src.only_when % 'new'}" if src.only_when else ""
    base = f"{spec.name}_{src.table}"
    # Text columns of the base table that feed this FTS table — an UPDATE OF
    # anything else (transcript status, counters) must not fire the trigger.
    watched = ", ".join(sorted({base for _, base, _ in src.columns}))
    return [
        f"CREATE TRIGGER IF NOT EXISTS {base}_ai AFTER INSERT ON {src.table}{when} BEGIN "
        f"INSERT INTO {spec.name}({cols}) VALUES ({vals}); END",
        f"CREATE TRIGGER IF NOT EXISTS {base}_au AFTER UPDATE OF {watched} ON {src.table} BEGIN "
        f"DELETE FROM {spec.name} WHERE id = old.{src.id_col}; "
        + (
            f"INSERT INTO {spec.name}({cols}) SELECT {vals} WHERE {src.only_when % 'new'}; END"
            if src.only_when
            else f"INSERT INTO {spec.name}({cols}) VALUES ({vals}); END"
        ),
        f"CREATE TRIGGER IF NOT EXISTS {base}_ad AFTER DELETE ON {src.table} BEGIN "
        f"DELETE FROM {spec.name} WHERE id = old.{src.id_col}; END",
    ]


def _rebuild_sql(spec: _FtsSpec) -> list[str]:
    out = [f"DELETE FROM {spec.name}"]
    for src in spec.sources:
        cols, vals = _insert_select(spec, src, "s")
        where = f" WHERE {src.only_when % 's'}" if src.only_when else ""
        out.append(f"INSERT INTO {spec.name}({cols}) SELECT {vals} FROM {src.table} s{where}")
    return out


# ---------------------------------------------------------------------------
# Probe, create, rebuild, drop
# ---------------------------------------------------------------------------

_TOKENIZERS = ("trigram remove_diacritics 1", "trigram")


def probe_fts5(conn: Connection) -> str | None:
    """Return the tokenizer string to use, or None when FTS5 (or its trigram
    tokenizer) is unavailable. Tries the diacritics-folding form first
    (SQLite ≥ 3.45), then plain trigram (≥ 3.34)."""
    if conn.dialect.name != "sqlite":
        return None
    for tokenize in _TOKENIZERS:
        try:
            conn.exec_driver_sql(
                f"CREATE VIRTUAL TABLE temp.__fts_probe USING fts5(x, tokenize='{tokenize}')"
            )
            conn.exec_driver_sql("DROP TABLE temp.__fts_probe")
            return tokenize
        except Exception:  # noqa: BLE001 — any failure means "not this tokenizer"
            try:
                conn.exec_driver_sql("DROP TABLE IF EXISTS temp.__fts_probe")
            except Exception:  # noqa: BLE001
                pass
    return None


def _existing_fts_tables(conn: Connection) -> set[str]:
    rows = conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'fts\\_%' ESCAPE '\\'"
    ).fetchall()
    return {r[0] for r in rows}


def ensure_index(bind: Engine | Connection) -> str:
    """Create any missing FTS tables and triggers, rebuild the ones just
    created, and record the backend for this process. Idempotent; safe to
    call from the lifespan, a migration and the test fixtures alike.
    Returns ``"fts5"`` or ``"like"``."""
    global _backend, _tokenize
    conn = bind.connect() if isinstance(bind, Engine) else bind
    owns = isinstance(bind, Engine)
    try:
        tokenize = probe_fts5(conn)
        if tokenize is None:
            _backend, _tokenize = BACKEND_LIKE, None
            logger.warning(
                "search: SQLite FTS5 (trigram) is not available in this Python's "
                "sqlite3 (%s); falling back to LIKE scans. Searches still work, "
                "without ranking or substring speed.",
                _sqlite_version(conn),
            )
            return _backend

        existing = _existing_fts_tables(conn)
        created: list[_FtsSpec] = []
        for spec in _SPECS.values():
            if spec.name not in existing:
                created.append(spec)
            conn.exec_driver_sql(_create_table_sql(spec, tokenize))
            for src in spec.sources:
                for stmt in _trigger_sql(spec, src):
                    conn.exec_driver_sql(stmt)
        for spec in created:
            for stmt in _rebuild_sql(spec):
                conn.exec_driver_sql(stmt)
        if owns:
            conn.commit()
        if created:
            logger.info(
                "search: created and rebuilt FTS5 tables %s (tokenize=%s)",
                [s.name for s in created], tokenize,
            )
        _backend, _tokenize = BACKEND_FTS5, tokenize
        return _backend
    finally:
        if owns:
            conn.close()


def ensure_index_for_url(db_url: str) -> str:
    """``ensure_index`` against a fresh engine for ``db_url`` (the lifespan
    reads ``settings.DATABASE_URL`` at boot, exactly as schema init does, so
    tests that repoint the URL index the same scratch database)."""
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    try:
        return ensure_index(engine)
    finally:
        engine.dispose()


def rebuild_index(bind: Engine | Connection) -> None:
    """Repopulate every FTS table from its base tables. Used by tests and
    by an operator after a bulk import that bypassed the ORM."""
    conn = bind.connect() if isinstance(bind, Engine) else bind
    owns = isinstance(bind, Engine)
    try:
        existing = _existing_fts_tables(conn)
        for spec in _SPECS.values():
            if spec.name in existing:
                for stmt in _rebuild_sql(spec):
                    conn.exec_driver_sql(stmt)
        if owns:
            conn.commit()
    finally:
        if owns:
            conn.close()


def drop_index(bind: Engine | Connection) -> None:
    """Drop every FTS table and trigger (migration downgrade, test teardown)."""
    global _backend, _tokenize
    conn = bind.connect() if isinstance(bind, Engine) else bind
    owns = isinstance(bind, Engine)
    try:
        for spec in _SPECS.values():
            for src in spec.sources:
                base = f"{spec.name}_{src.table}"
                for suffix in ("ai", "au", "ad"):
                    conn.exec_driver_sql(f"DROP TRIGGER IF EXISTS {base}_{suffix}")
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS {spec.name}")
        if owns:
            conn.commit()
    finally:
        if owns:
            conn.close()
    _backend, _tokenize = None, None


def current_backend() -> str:
    """What this process searches with. ``"like"`` until ``ensure_index`` has
    found FTS5, which the FastAPI lifespan does at startup."""
    return _backend or BACKEND_LIKE


def _sqlite_version(conn: Connection) -> str:
    try:
        return str(conn.exec_driver_sql("select sqlite_version()").scalar())
    except Exception:  # noqa: BLE001
        return "unknown"


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def match_expression(q: str) -> str | None:
    """Turn free text into an FTS5 MATCH expression: every whitespace-separated
    token of at least three characters, quoted (so FTS5 syntax characters in
    user input are literal) and AND-ed. None when no token is long enough —
    the caller then uses LIKE."""
    tokens = [t for t in q.split() if len(t) >= MIN_MATCH_CHARS]
    if not tokens:
        return None
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in tokens)


@dataclass
class SearchItem:
    id: str
    title: str
    subtitle: str
    href: str
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "subtitle": self.subtitle, "href": self.href, "score": self.score}


def _bm25(spec: _FtsSpec) -> str:
    weights = ", ".join(f"{w:g}" for w in spec.weights)
    return f"bm25({spec.name}, {weights})"


# Tenant anchors as SQL fragments over the FTS alias `f`, parameter :t.
_TENANT_SQL = {
    "documents": (
        "JOIN documents d ON d.document_id = f.id "
        "JOIN document_visibility v ON v.video_id = d.video_id AND v.tenant_id = :t"
    ),
    "knowledge": (
        "JOIN documents d ON d.document_id = f.id "
        "JOIN document_visibility v ON v.video_id = d.video_id AND v.tenant_id = :t"
    ),
    "jobs": "JOIN jobs d ON d.id = f.id AND d.tenant_id = :t",
    "channels": (
        "JOIN channels d ON d.channel_id = f.id AND d.channel_id IN ("
        "SELECT channel_id FROM channel_subscriptions WHERE tenant_id = :t "
        "UNION SELECT dd.channel_id FROM documents dd "
        "JOIN document_visibility vv ON vv.video_id = dd.video_id "
        "WHERE vv.tenant_id = :t AND dd.channel_id IS NOT NULL)"
    ),
}

_QA_TENANT_SQL = (
    "LEFT JOIN qa_exchanges qj ON f.surface = 'job' AND qj.id = f.id AND qj.tenant_id = :t "
    "LEFT JOIN library_qa_exchanges ql ON f.surface = 'library' AND ql.id = f.id AND ql.tenant_id = :t "
    "LEFT JOIN qa_history_exchanges qh ON f.surface = 'history' AND qh.id = f.id AND qh.tenant_id = :t "
    "WHERE (qj.id IS NOT NULL OR ql.id IS NOT NULL OR qh.id IS NOT NULL) AND "
)


def _fts_hits(db: Session, kind: str, match: str, tenant_id: str, limit: int) -> list[tuple[str, float]]:
    spec = _SPECS[kind]
    n = limit * _OVERFETCH
    if kind == "qa":
        sql = (
            f"SELECT f.id, {_bm25(spec)} AS score, "
            f"coalesce(qj.created_at, ql.created_at, qh.created_at) AS created_at "
            f"FROM {spec.name} f {_QA_TENANT_SQL} {spec.name} MATCH :m "
            f"ORDER BY score, created_at DESC LIMIT :n"
        )
    else:
        sql = (
            f"SELECT f.id, {_bm25(spec)} AS score, d.created_at AS created_at "
            f"FROM {spec.name} f {_TENANT_SQL[kind]} "
            f"WHERE {spec.name} MATCH :m "
            f"ORDER BY score, created_at DESC LIMIT :n"
        )
    rows = db.execute(text(sql), {"m": match, "t": tenant_id, "n": n}).fetchall()
    # bm25 is negative-is-better; expose the usual higher-is-better.
    seen: set[str] = set()
    out: list[tuple[str, float]] = []
    for row_id, score, _created in rows:
        if row_id in seen:
            continue
        seen.add(row_id)
        out.append((row_id, -float(score)))
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Per-group search: FTS hits hydrated through the ORM, or a LIKE scan
# ---------------------------------------------------------------------------


def _visible_documents(db: Session, tenant_id: str):
    return db.query(Document).join(
        DocumentVisibility,
        (DocumentVisibility.video_id == Document.video_id) & (DocumentVisibility.tenant_id == tenant_id),
    )


def _visible_channels(db: Session, tenant_id: str):
    from sqlalchemy import union

    subscribed = db.query(ChannelSubscription.channel_id).filter(ChannelSubscription.tenant_id == tenant_id)
    from_docs = (
        db.query(Document.channel_id)
        .join(DocumentVisibility, DocumentVisibility.video_id == Document.video_id)
        .filter(DocumentVisibility.tenant_id == tenant_id, Document.channel_id.isnot(None))
    )
    return db.query(Channel).filter(Channel.channel_id.in_(union(subscribed, from_docs)))


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _fmt_date(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def _document_item(doc: Document, score: float) -> SearchItem:
    bits = [doc.channel_name or doc.source_type or "document", _fmt_date(doc.published_at)]
    return SearchItem(
        id=doc.document_id,
        title=doc.title or "(untitled)",
        subtitle=" · ".join(b for b in bits if b),
        href=f"/library?video={doc.video_id or doc.document_id}",
        score=score,
    )


def _knowledge_item(doc: Document, score: float) -> SearchItem:
    return SearchItem(
        id=doc.document_id,
        title=doc.title or "(untitled)",
        subtitle=" · ".join(b for b in ["Knowledge report", doc.channel_name or ""] if b),
        href=f"/library?video={doc.video_id or doc.document_id}&view=knowledge",
        score=score,
    )


def _job_item(job: Job, score: float) -> SearchItem:
    return SearchItem(
        id=job.id,
        title=job.topic or f"{job.job_type} run",
        subtitle=" · ".join(b for b in [job.job_type or "", job.status or "", _fmt_date(job.created_at)] if b),
        href=f"/jobs/{job.id}",
        score=score,
    )


def _channel_item(ch: Channel, score: float) -> SearchItem:
    subs = f"{ch.subscriber_count:,} subscribers" if ch.subscriber_count else "channel"
    return SearchItem(
        id=ch.channel_id, title=ch.name, subtitle=subs, href=f"/library/channels/{ch.channel_id}", score=score
    )


_QA_SURFACES = {
    "job": (QAExchange, "Q&A on a run"),
    "library": (LibraryQAExchange, "Library Q&A"),
    "history": (QAHistoryExchange, "Q&A history"),
}


def _qa_item(surface: str, row: Any, score: float) -> SearchItem:
    _, label = _QA_SURFACES[surface]
    if surface == "job":
        href = f"/jobs/{row.job_id}?exchange={row.id}"
    elif surface == "library":
        href = f"/library/qa?exchange={row.id}"
    else:
        href = f"/qa-history?exchange={row.id}"
    question = " ".join((row.question or "").split())
    return SearchItem(
        id=row.id,
        title=question[:160] + ("…" if len(question) > 160 else ""),
        subtitle=" · ".join(b for b in [label, _fmt_date(row.created_at)] if b),
        href=href,
        score=score,
    )


def _hydrate(rows: Iterable[Any], id_attr: str, hits: list[tuple[str, float]], build) -> list[SearchItem]:
    by_id = {getattr(r, id_attr): r for r in rows}
    return [build(by_id[i], score) for i, score in hits if i in by_id]


def _search_documents(db: Session, tenant_id: str, q: str, match: str | None, limit: int) -> list[SearchItem]:
    if match:
        hits = _fts_hits(db, "documents", match, tenant_id, limit)
        rows = _visible_documents(db, tenant_id).filter(Document.document_id.in_([i for i, _ in hits])).all()
        return _hydrate(rows, "document_id", hits, _document_item)
    like = _like(q)
    rows = (
        _visible_documents(db, tenant_id)
        .filter(or_(Document.title.ilike(like, escape="\\"), Document.description.ilike(like, escape="\\")))
        .order_by(Document.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_document_item(r, 0.0) for r in rows]


def _search_knowledge(db: Session, tenant_id: str, q: str, match: str | None, limit: int) -> list[SearchItem]:
    if match:
        hits = _fts_hits(db, "knowledge", match, tenant_id, limit)
        rows = _visible_documents(db, tenant_id).filter(Document.document_id.in_([i for i, _ in hits])).all()
        return _hydrate(rows, "document_id", hits, _knowledge_item)
    like = _like(q)
    rows = (
        _visible_documents(db, tenant_id)
        .filter(Document.knowledge_report_md.isnot(None), Document.knowledge_report_md.ilike(like, escape="\\"))
        .order_by(Document.knowledge_extracted_at.desc())
        .limit(limit)
        .all()
    )
    return [_knowledge_item(r, 0.0) for r in rows]


def _search_jobs(db: Session, tenant_id: str, q: str, match: str | None, limit: int) -> list[SearchItem]:
    base = db.query(Job).filter(Job.tenant_id == tenant_id)
    if match:
        hits = _fts_hits(db, "jobs", match, tenant_id, limit)
        rows = base.filter(Job.id.in_([i for i, _ in hits])).all()
        return _hydrate(rows, "id", hits, _job_item)
    like = _like(q)
    rows = (
        base.filter(or_(Job.topic.ilike(like, escape="\\"), Job.search_instructions.ilike(like, escape="\\")))
        .order_by(Job.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_job_item(r, 0.0) for r in rows]


def _search_channels(db: Session, tenant_id: str, q: str, match: str | None, limit: int) -> list[SearchItem]:
    base = _visible_channels(db, tenant_id)
    if match:
        hits = _fts_hits(db, "channels", match, tenant_id, limit)
        rows = base.filter(Channel.channel_id.in_([i for i, _ in hits])).all()
        return _hydrate(rows, "channel_id", hits, _channel_item)
    like = _like(q)
    rows = base.filter(Channel.name.ilike(like, escape="\\")).order_by(Channel.created_at.desc()).limit(limit).all()
    return [_channel_item(r, 0.0) for r in rows]


def _search_qa(db: Session, tenant_id: str, q: str, match: str | None, limit: int) -> list[SearchItem]:
    if match:
        hits = _fts_hits(db, "qa", match, tenant_id, limit)
        ids = [i for i, _ in hits]
        found: dict[str, tuple[str, Any]] = {}
        for surface, (model, _label) in _QA_SURFACES.items():
            for row in db.query(model).filter(model.tenant_id == tenant_id, model.id.in_(ids)).all():
                found.setdefault(row.id, (surface, row))
        return [_qa_item(found[i][0], found[i][1], score) for i, score in hits if i in found]
    like = _like(q)
    candidates: list[tuple[str, Any]] = []
    for surface, (model, _label) in _QA_SURFACES.items():
        rows = (
            db.query(model)
            .filter(model.tenant_id == tenant_id, model.question.ilike(like, escape="\\"))
            .order_by(model.created_at.desc())
            .limit(limit)
            .all()
        )
        candidates.extend((surface, r) for r in rows)
    candidates.sort(key=lambda sr: sr[1].created_at or datetime.min, reverse=True)
    return [_qa_item(s, r, 0.0) for s, r in candidates[:limit]]


_GROUP_SEARCHERS = {
    "jobs": _search_jobs,
    "documents": _search_documents,
    "channels": _search_channels,
    "qa": _search_qa,
    "knowledge": _search_knowledge,
}


def search(
    db: Session,
    tenant_id: str,
    q: str,
    *,
    types: Iterable[str] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Grouped, tenant-scoped keyword search.

    Returns ``{"q", "backend", "groups": [{"type", "items": [...]}]}`` with one
    group per requested type, in the order of ``SEARCH_TYPES``. ``backend`` is
    the engine actually used for THIS query: ``"like"`` also when FTS5 is
    present but no token reached three characters.
    """
    q = " ".join((q or "").split())
    wanted = [t for t in SEARCH_TYPES if t in set(types or SEARCH_TYPES)]
    groups: list[dict[str, Any]] = []
    if not q:
        return {"q": q, "backend": current_backend(), "groups": [{"type": t, "items": []} for t in wanted]}

    match = match_expression(q) if current_backend() == BACKEND_FTS5 else None
    for kind in wanted:
        items = _GROUP_SEARCHERS[kind](db, tenant_id, q, match, limit)
        groups.append({"type": kind, "items": [i.as_dict() for i in items]})
    return {"q": q, "backend": BACKEND_FTS5 if match else BACKEND_LIKE, "groups": groups}
