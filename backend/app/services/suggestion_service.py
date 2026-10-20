"""Question suggestions: "You might ask…" (S-8.4.1 / M4).

Plan: docs/plans/m4-question-suggestions.md. Three to five next questions
for a context (a run, one source, or the whole library), from two pools:

(a) **Past questions** the caller asked elsewhere, nearest to the context in
    ``qa_library_global`` (always tenant-filtered; the fail-closed filter in
    ``chroma_service.query_qa_collection`` is what keeps another tenant's
    questions out).
(b) **Generated questions** grounded in a summary of the context (report
    headings, knowledge topics, source titles) from the
    ``qa_suggest_questions`` use case: the volume tier, reasoning off.

Both pools are deduplicated against what was already asked on this context
and against each other (cosine on the multilingual embedder the library
already uses), then diversified with maximal marginal relevance so the five
differ in subject, not just wording.

Results are cached per ``(tenant, context)`` in ``suggestion_cache`` with a
fingerprint of the context's inputs (the latest exchange on it, the report,
the knowledge state); a changed fingerprint or an expired window recomputes.
A failed or unavailable generator degrades to pool (a) and is not cached, so
the next open tries again.

The prompt lives here rather than under ``app/agents/prompts`` (that
package belongs to the report and Q&A agents). It reads summaries, not
transcript text, so the visual and temporal contracts do not apply; the
English-output contract does, because topics and titles can be in any
language.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session

from app.agents.prompts.shared import ENGLISH_OUTPUT_CONTRACT
from app.config import settings
from app.models.document import Document
from app.models.job_video import JobVideo
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.models.suggestion_cache import SuggestionCache
from app.models.user import User
from app.services import chroma_service, job_service, quota_metering_service, report_service, visibility_service
from app.services.llm_service import get_llm_for, response_text

logger = logging.getLogger(__name__)

USE_CASE = "qa_suggest_questions"

#: How many suggestions a context gets.
MAX_SUGGESTIONS = 5
#: How many questions the generator is asked for (a little over, for MMR).
GENERATE_N = 7
#: Nearest past questions considered from ``qa_library_global``.
HISTORY_K = 12
#: Output cap. Reasoning is off for this use case; with it on, OpenAI
#: models count reasoning tokens against this cap (the D-052 trap).
MAX_COMPLETION_TOKENS = 900
#: A candidate this close to a question already asked here is a repeat.
ASKED_DUPLICATE = 0.88
#: Two candidates this close are the same question in other words.
CANDIDATE_DUPLICATE = 0.86
#: MMR trade-off: 1.0 is pure relevance, 0.0 pure novelty.
MMR_LAMBDA = 0.65

SourceKind = Literal["generated", "history"]

SUGGEST_PROMPT = """You suggest the next questions a researcher could ask about a body of sources they chose themselves.

{english}

WHAT THEY ARE LOOKING AT:
{context}

QUESTIONS THEY ALREADY ASKED HERE (do not repeat or rephrase these):
{asked}

Write {n} questions they could ask next. Each one must:
- be answerable from these sources (the summary above is all you know about them);
- cover a different subject from the others: spread them across the topics, do not ask the same thing in other words;
- be useful for their next step: comparisons, disagreements between sources, causes, consequences, what changed over time, what a named person or source claimed and why;
- be one sentence, at most 25 words, and name the specific subject (never "this topic" or "the video").

For each, add a rationale of at most 15 words saying why it is worth asking.

Return ONLY a JSON object, no prose and no code fences:
{{"suggestions": [{{"question": "...", "rationale": "..."}}]}}"""


class ContextError(ValueError):
    """The ``context`` parameter is malformed (422)."""


class ContextNotFound(LookupError):
    """The context names something the caller cannot see (404)."""


class ContextNotReady(RuntimeError):
    """The run has not finished, so it cannot be asked about yet (400)."""


@dataclass
class Context:
    kind: Literal["job", "document", "library"]
    ref_id: str | None
    #: Canonical form, also the cache key: ``job:<id>``, ``document:<id>``, ``library``.
    key: str
    #: Lines describing the context to the generator.
    summary: list[str]
    #: What the embedder compares candidates with (and the history query).
    query_text: str
    #: Questions already asked on this context, newest first.
    asked: list[str]
    #: Changes when the context's inputs change; a cache row with another one is stale.
    fingerprint: str
    #: Sources behind the context. Zero means there is nothing to ask about.
    sources: int = 1


@dataclass
class Candidate:
    question: str
    rationale: str
    source: SourceKind
    #: For history items: where the original exchange lives.
    origin: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Context


_KNOWLEDGE_TOPICS = 14
_TITLES = 12
_HEADINGS = 14
_ASKED = 40


def parse_context(raw: str) -> tuple[str, str | None]:
    value = (raw or "").strip()
    if value == "library":
        return "library", None
    kind, sep, ref = value.partition(":")
    if sep and kind in ("job", "document") and ref.strip():
        return kind, ref.strip()
    raise ContextError("context must be job:<id>, document:<id> or library")


def _knowledge_topics(doc: Document, limit: int = 6) -> list[str]:
    if not doc.extracted_knowledge_json:
        return []
    try:
        data = json.loads(doc.extracted_knowledge_json)
    except (TypeError, ValueError):
        return []
    out: list[str] = []
    for key in ("topics", "concepts"):
        for item in data.get(key) or []:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and name.strip() and name.strip() not in out:
                out.append(name.strip())
            if len(out) >= limit:
                return out
    return out


_HEADING_RE = re.compile(r"<h([23])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _report_headings(report_path: str | None) -> list[str]:
    if not report_path:
        return []
    html = report_service.get_report_html(report_path)
    if not html:
        return []
    out: list[str] = []
    for _level, inner in _HEADING_RE.findall(html):
        text = re.sub(r"\s+", " ", _TAG_RE.sub("", inner)).strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= _HEADINGS:
            break
    return out


def _json_list(raw: str | None) -> list[str]:
    """``jobs.channel_list`` is a JSON array stored as text."""
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def _dedupe_keep_order(items: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        k = item.casefold()
        if k not in seen:
            seen.add(k)
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def check_context(db: Session, user: User, raw: str) -> str:
    """The canonical key for ``raw`` if the caller may use it; raises like
    ``resolve_context`` but reads nothing beyond ownership."""
    kind, ref = parse_context(raw)
    if kind == "job":
        job = job_service.get_job(db, ref, tenant_id=user.id)
        if job is None:
            raise ContextNotFound("Job not found")
        return f"job:{job.id}"
    if kind == "document":
        doc = visibility_service.visible_document(db, user.id, ref)
        if doc is None:
            raise ContextNotFound("Document not found")
        return f"document:{doc.document_id}"
    return "library"


def resolve_context(db: Session, user: User, raw: str) -> Context:
    kind, ref = parse_context(raw)
    if kind == "job":
        return _job_context(db, user, ref)  # type: ignore[arg-type]
    if kind == "document":
        return _document_context(db, user, ref)  # type: ignore[arg-type]
    return _library_context(db, user)


def _job_context(db: Session, user: User, job_id: str) -> Context:
    job = job_service.get_job(db, job_id, tenant_id=user.id)
    if job is None:
        raise ContextNotFound("Job not found")
    if job.status != "completed":
        raise ContextNotReady("Job is not completed yet")
    docs = (
        db.query(Document)
        .join(JobVideo, JobVideo.document_id == Document.document_id)
        .filter(JobVideo.job_id == job.id, JobVideo.approved.is_(True))
        .all()
    )
    titles = _dedupe_keep_order([d.title for d in docs if d.title], _TITLES)
    topics = _dedupe_keep_order([t for d in docs for t in _knowledge_topics(d)], _KNOWLEDGE_TOPICS)
    headings = _report_headings(job.report_path)
    label = job.topic or ("Channels: " + ", ".join(_json_list(job.channel_list)))
    asked_rows = (
        db.query(QAExchange)
        .filter(QAExchange.job_id == job.id, QAExchange.tenant_id == user.id)
        .order_by(QAExchange.created_at.desc())
        .limit(_ASKED)
        .all()
    )
    summary = [f"A research run on: {label} ({len(docs)} sources)."]
    if headings:
        summary.append("Its report's sections: " + "; ".join(headings) + ".")
    if topics:
        summary.append("Topics the sources cover: " + "; ".join(topics) + ".")
    if titles:
        summary.append("Some of the sources: " + "; ".join(titles) + ".")
    latest = asked_rows[0].id if asked_rows else "-"
    return Context(
        kind="job",
        ref_id=job.id,
        key=f"job:{job.id}",
        summary=summary,
        query_text=" ".join([label, *headings[:6], *topics[:6]]),
        asked=[r.question for r in asked_rows],
        fingerprint=_fingerprint(len(asked_rows), latest, job.completed_at, job.report_path, len(topics)),
        sources=len(docs),
    )


def _document_context(db: Session, user: User, raw_id: str) -> Context:
    doc = visibility_service.visible_document(db, user.id, raw_id)
    if doc is None:
        raise ContextNotFound("Document not found")
    topics = _knowledge_topics(doc, limit=_KNOWLEDGE_TOPICS)
    channel = doc.channel_name or ""
    summary = [f"One source: {doc.title}" + (f", from {channel}" if channel else "") + "."]
    if topics:
        summary.append("What it covers: " + "; ".join(topics) + ".")
    elif doc.description:
        summary.append("Its description: " + doc.description[:600])
    return Context(
        kind="document",
        ref_id=doc.document_id,
        key=f"document:{doc.document_id}",
        summary=summary,
        query_text=" ".join([doc.title or "", *topics[:8]]),
        asked=[],
        fingerprint=_fingerprint(doc.knowledge_extracted_at, len(topics)),
    )


def _library_context(db: Session, user: User) -> Context:
    docs = (
        db.query(Document)
        .filter(Document.document_id.in_(visibility_service.visible_document_ids(db, user.id)))
        .order_by(Document.published_at.desc().nullslast())
        .limit(40)
        .all()
    )
    titles = _dedupe_keep_order([d.title for d in docs if d.title], _TITLES)
    topics = _dedupe_keep_order([t for d in docs for t in _knowledge_topics(d, limit=3)], _KNOWLEDGE_TOPICS)
    asked_rows = (
        db.query(LibraryQAExchange)
        .filter(LibraryQAExchange.tenant_id == user.id)
        .order_by(LibraryQAExchange.created_at.desc())
        .limit(_ASKED)
        .all()
    )
    summary = [f"Their whole library: {len(docs)}{'+' if len(docs) == 40 else ''} sources they ingested."]
    if topics:
        summary.append("Topics across it: " + "; ".join(topics) + ".")
    if titles:
        summary.append("Recent sources: " + "; ".join(titles) + ".")
    latest = asked_rows[0].id if asked_rows else "-"
    newest = docs[0].document_id if docs else "-"
    return Context(
        kind="library",
        ref_id=None,
        key="library",
        summary=summary,
        query_text=" ".join([*topics[:8], *titles[:4]]),
        asked=[r.question for r in asked_rows],
        fingerprint=_fingerprint(len(asked_rows), latest, len(docs), newest),
        sources=len(docs),
    )


# ---------------------------------------------------------------------------
# Pools


def _question_of(text: str) -> str:
    """``qa_library_global`` stores ``"Q: …\\n\\nA: …"`` (chroma_service)."""
    head = text.split("\n\nA:", 1)[0]
    return head[3:].strip() if head.startswith("Q: ") else head.strip()


def history_pool(ctx: Context, tenant_id: str, k: int = HISTORY_K) -> list[Candidate]:
    """Questions the caller asked elsewhere that sit near this context.

    Always tenant-scoped. Exchanges on this same context are excluded here
    (they are ``ctx.asked``, which the selection drops anyway)."""
    if not ctx.query_text.strip():
        return []
    hits = chroma_service.query_qa_collection(ctx.query_text, top_k=k, tenant_id=tenant_id)
    out: list[Candidate] = []
    for hit in hits:
        meta = hit.get("metadata") or {}
        if ctx.kind == "job" and meta.get("source") == "job" and meta.get("job_id") == ctx.ref_id:
            continue
        if ctx.kind == "library" and meta.get("source") == "library":
            continue
        question = _question_of(hit.get("text") or "")
        if not question:
            continue
        where = {"job": "in another run", "library": "of the whole library", "history": "in your Q&A history"}
        out.append(
            Candidate(
                question=question,
                rationale=f"You asked this {where.get(meta.get('source'), 'before')}; ask it here too.",
                source="history",
                origin={k2: meta.get(k2) for k2 in ("source", "exchange_id", "job_id") if meta.get(k2)},
            )
        )
    return out


def _parse_suggestions(text: str) -> list[dict]:
    body = (text or "").strip()
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body)
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(body[start : end + 1])
    except ValueError:
        return []
    items = data.get("suggestions") if isinstance(data, dict) else None
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        q = item.get("question")
        if isinstance(q, str) and q.strip():
            r = item.get("rationale")
            out.append({"question": q.strip()[:300], "rationale": (r.strip() if isinstance(r, str) else "")[:200]})
    return out


def _usage(response) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    return 0, 0


def build_prompt(ctx: Context, n: int = GENERATE_N) -> str:
    asked = "\n".join(f"- {q}" for q in ctx.asked[:20]) or "(none yet)"
    return SUGGEST_PROMPT.format(english=ENGLISH_OUTPUT_CONTRACT, context="\n".join(ctx.summary), asked=asked, n=n)


def generated_pool(db: Session, ctx: Context, user: User, n: int = GENERATE_N) -> list[Candidate]:
    """Questions from the generator. Raises on a failed call; the caller
    decides what a failure means (it degrades to the history pool)."""
    client = get_llm_for(USE_CASE, temperature=0.3, max_tokens=MAX_COMPLETION_TOKENS, tenant_id=user.id, db=db)
    response = client.invoke([HumanMessage(content=build_prompt(ctx, n))])
    tokens_in, tokens_out = _usage(response)
    try:
        if tokens_in:
            quota_metering_service.record_usage(db, user.id, "llm_tokens_in", tokens_in)
        if tokens_out:
            quota_metering_service.record_usage(db, user.id, "llm_tokens_out", tokens_out)
    except Exception:  # pragma: no cover - metering never breaks the feature
        logger.exception("suggestions: token metering failed")
    items = _parse_suggestions(response_text(response))
    return [Candidate(question=i["question"], rationale=i["rationale"], source="generated") for i in items]


# ---------------------------------------------------------------------------
# Selection


def _encode(texts: list[str]) -> list[list[float]]:
    """The library's embedder. A seam: tests swap in a cheap one."""
    from app.services import embedding_service

    return embedding_service.encode(texts)


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def select(
    candidates: list[Candidate],
    *,
    query_text: str,
    asked: list[str],
    k: int = MAX_SUGGESTIONS,
    lam: float = MMR_LAMBDA,
    encode: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[Candidate]:
    """Drop repeats of what was asked and of each other, then MMR."""
    if not candidates:
        return []
    enc = encode or _encode
    texts = [query_text or " ", *asked, *(c.question for c in candidates)]
    vectors = enc(texts)
    q_vec = vectors[0]
    asked_vecs = vectors[1 : 1 + len(asked)]
    cand_vecs = vectors[1 + len(asked) :]

    pool: list[tuple[Candidate, list[float], float]] = []
    for cand, vec in zip(candidates, cand_vecs):
        if any(_cos(vec, a) >= ASKED_DUPLICATE for a in asked_vecs):
            continue
        if any(_cos(vec, kept) >= CANDIDATE_DUPLICATE for _c, kept, _r in pool):
            continue
        pool.append((cand, vec, _cos(vec, q_vec)))

    chosen: list[tuple[Candidate, list[float], float]] = []
    while pool and len(chosen) < k:
        def score(item):
            _c, vec, rel = item
            novelty = max((_cos(vec, v) for _c2, v, _r in chosen), default=0.0)
            return lam * rel - (1 - lam) * novelty

        best = max(pool, key=score)
        chosen.append(best)
        pool.remove(best)
    return [c for c, _v, _r in chosen]


# ---------------------------------------------------------------------------
# Entry point


def _ttl() -> timedelta:
    return timedelta(minutes=max(0, settings.SUGGESTIONS_CACHE_TTL_MIN))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def suggestions_for(
    db: Session,
    user: User,
    raw_context: str,
    *,
    generator_available: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """``{context, suggestions: [{question, rationale, source}], cached, generated}``."""
    ctx = resolve_context(db, user, raw_context)
    if ctx.sources == 0:
        # An empty library (or a run whose sources are gone): a model would
        # only invent questions about nothing, and no past question can be
        # answered here either. No call, nothing cached.
        return {"context": ctx.key, "suggestions": [], "generated": False, "cached": False}
    now = now or datetime.now(timezone.utc)
    row = (
        db.query(SuggestionCache)
        .filter(SuggestionCache.tenant_id == user.id, SuggestionCache.context_key == ctx.key)
        .first()
    )
    if row and row.fingerprint == ctx.fingerprint and now - _aware(row.computed_at) < _ttl():
        try:
            payload = json.loads(row.payload_json)
            return {**payload, "cached": True}
        except ValueError:
            logger.warning("suggestions: unreadable cache row for %s; recomputing", ctx.key)

    generated: list[Candidate] = []
    generated_ok = False
    if generator_available:
        try:
            generated = generated_pool(db, ctx, user)
            generated_ok = bool(generated)
        except Exception:
            logger.exception("suggestions: generator failed for %s; history only", ctx.key)
    try:
        history = history_pool(ctx, user.id)
    except Exception:
        logger.exception("suggestions: history pool failed for %s", ctx.key)
        history = []

    picked = select(generated + history, query_text=ctx.query_text, asked=ctx.asked)
    payload = {
        "context": ctx.key,
        "suggestions": [
            {"question": c.question, "rationale": c.rationale, "source": c.source, "origin": c.origin or None}
            for c in picked
        ],
        "generated": generated_ok,
    }
    # Only a complete answer is cached: after a failed or unavailable
    # generator the next open should try again.
    if generated_ok:
        if row is None:
            row = SuggestionCache(tenant_id=user.id, context_key=ctx.key)
            db.add(row)
        row.fingerprint = ctx.fingerprint
        row.payload_json = json.dumps(payload)
        row.computed_at = now
        db.commit()
    return {**payload, "cached": False}
