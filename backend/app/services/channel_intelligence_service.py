"""Channel intelligence — what a channel says, over the reader's own view of
it (E-8.7 / S-8.7.2; plan: docs/plans/m7-channel-intelligence.md).

Every figure is computed over the documents of the channel that the tenant
can see (D-063 / D-070, ``visibility_service.visible_document_ids``). Two
readers following the same channel can therefore see different numbers,
which is correct. An empty visible set yields an empty aggregate, never the
channel's global one.

The document-derived part (cadence, durations, topics, concepts, keyword
cloud, stance) is cached per (channel, tenant) under a fingerprint of its
inputs, so new documents or new knowledge artifacts invalidate it and
nothing else does. The Q&A part is cheap and computed live on every read.

Computed in the request, not in a Celery task: the worker runs
``--pool=solo`` and is routinely busy for hours with ingest, so a queued
aggregate could wait behind a whole job. The heavy step (TF-IDF over
transcripts) is bounded by ``MAX_KEYWORD_DOCS`` and ``MAX_CHARS_PER_DOC``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.models.channel_intelligence_cache import ChannelIntelligenceCache
from app.models.document import Document
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.models.transcript_cache import TranscriptCache
from app.services import visibility_service

logger = logging.getLogger(__name__)

TOP_LABELS = 25
TOP_KEYWORDS = 60
EXAMPLES_PER_LABEL = 8
MAX_KEYWORD_DOCS = 500
MAX_CHARS_PER_DOC = 40_000
MAX_EXCHANGES_SCANNED = 2_000
RECENT_EXCHANGES = 10
# Bump when the cached payload's shape changes, so rows written by older code
# are recomputed rather than served without the new fields.
PAYLOAD_VERSION = 2

DURATION_BUCKETS: list[tuple[str, float, float | None]] = [
    ("Under 5 min", 0, 5),
    ("5–15 min", 5, 15),
    ("15–30 min", 15, 30),
    ("30–60 min", 30, 60),
    ("1–2 h", 60, 120),
    ("2 h+", 120, None),
]

# Spoken filler that survives English stop-word lists and would otherwise
# top every transcript cloud.
TRANSCRIPT_FILLER = frozenset(
    """
    um uh uhm erm hmm mhm yeah yep yes okay ok alright gonna wanna gotta kinda sorta
    like just really actually basically literally know think going right thing things
    stuff lot lots mean say said saying got get getting want need way much even still
    back make made let sure maybe pretty little guys today video videos channel subscribe
    music applause laughter welcome thanks thank look looking come came went goes kind
    bit good great yes something anything everything somebody someone people time times
    """.split()
)
# English function words. Not scikit-learn's ENGLISH_STOP_WORDS: that is the
# Glasgow list, which drops content words such as "interest", "system",
# "fire" and "bill" — exactly what a channel's cloud should show.
FUNCTION_WORDS = frozenset(
    """
    a about above after again against all am an and any are aren as at be because been before
    being below between both but by can cannot could couldn did didn do does doesn doing don down
    during each few for from further had hadn has hasn have haven having he her here hers herself
    him himself his how i if in into is isn it its itself just me more most my myself no nor not
    now of off on once only or other ought our ours ourselves out over own same she should shouldn
    so some such than that the their theirs them themselves then there these they this those
    through to too under until up very was wasn we were weren what when where which while who whom
    why will with won would wouldn you your yours yourself yourselves also however therefore thus
    may might must shall upon within without whether among across along around since though
    although unless whose via per etc ll ve re
    """.split()
)
TOKEN_PATTERN = r"(?u)\b[^\W\d_]{3,}\b"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def visible_channel_documents(db: Session, tenant_id: str, channel_id: str) -> list[Document]:
    return (
        db.query(Document)
        .filter(
            Document.channel_id == channel_id,
            Document.document_id.in_(visibility_service.visible_document_ids(db, tenant_id)),
        )
        .all()
    )


def _transcript_states(db: Session, doc_ids: list[str]) -> dict[str, str]:
    if not doc_ids:
        return {}
    return {
        row.document_id: (row.fetched_at.isoformat() if row.fetched_at else "")
        for row in db.query(TranscriptCache.document_id, TranscriptCache.fetched_at).filter(
            TranscriptCache.document_id.in_(doc_ids)
        )
    }


def fingerprint(docs: list[Document], transcripts: dict[str, str]) -> str:
    """Hash of everything the document-derived aggregate reads."""
    h = hashlib.sha256(f"payload-v{PAYLOAD_VERSION}|".encode())
    for d in sorted(docs, key=lambda x: x.document_id):
        h.update(
            "|".join(
                [
                    d.document_id,
                    d.knowledge_extracted_at.isoformat() if d.knowledge_extracted_at else "",
                    d.published_at.isoformat() if d.published_at else "",
                    str(d.duration_seconds or ""),
                    transcripts.get(d.document_id, ""),
                    str(len(d.source_metadata_json or "")),
                ]
            ).encode()
        )
        h.update(b"\n")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------

def _month(dt: datetime) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def _month_range(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def cadence(docs: list[Document]) -> dict:
    counts = Counter(_month(d.published_at) for d in docs if d.published_at)
    undated = sum(1 for d in docs if not d.published_at)
    if not counts:
        return {"months": [], "undated": undated}
    months = _month_range(min(counts), max(counts))
    return {"months": [{"month": m, "count": counts.get(m, 0)} for m in months], "undated": undated}


def durations(docs: list[Document]) -> dict:
    minutes = [d.duration_seconds / 60 for d in docs if d.duration_seconds]
    buckets = []
    for label, lo, hi in DURATION_BUCKETS:
        n = sum(1 for m in minutes if m >= lo and (hi is None or m < hi))
        buckets.append({"label": label, "min_minutes": lo, "max_minutes": hi, "count": n})
    return {
        "buckets": buckets,
        "unknown": len(docs) - len(minutes),
        "median_minutes": round(statistics.median(minutes), 1) if minutes else None,
    }


def _ref(doc: Document) -> dict:
    return {"id": doc.document_id, "title": doc.title, "url": doc.url}


def _knowledge(doc: Document) -> dict:
    if not doc.extracted_knowledge_json:
        return {}
    try:
        value = json.loads(doc.extracted_knowledge_json)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def display_label(spellings) -> str:
    """The spelling to show for a label seen in several casings: the most
    frequent, ties broken toward more capitals ("Monetary policy" over
    "monetary policy"), then alphabetically, so it never depends on row order."""
    return max(spellings.items(), key=lambda kv: (kv[1], sum(ch.isupper() for ch in kv[0]), [-ord(ch) for ch in kv[0]]))[0]


def _clean_label(raw) -> str:
    if isinstance(raw, dict):
        raw = raw.get("name") or raw.get("label") or raw.get("text") or ""
    return " ".join(str(raw or "").split()).strip(" .;:,")


def label_counts(docs: list[Document], key: str) -> list[dict]:
    """Labels from knowledge artifacts, merged case-insensitively, counted
    once per document, each with a few example documents."""
    by_key: dict[str, list[Document]] = defaultdict(list)
    spellings: dict[str, Counter] = defaultdict(Counter)
    for d in docs:
        seen: set[str] = set()
        for raw in _knowledge(d).get(key) or []:
            label = _clean_label(raw)
            if len(label) < 2:
                continue
            k = label.lower()
            spellings[k][label] += 1
            if k in seen:
                continue
            seen.add(k)
            by_key[k].append(d)
    ranked = sorted(by_key.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:TOP_LABELS]
    return [
        {
            "label": display_label(spellings[k]),
            "documents": len(ds),
            "examples": [_ref(d) for d in ds[:EXAMPLES_PER_LABEL]],
        }
        for k, ds in ranked
    ]


def _transcript_text(segments_json: str) -> str:
    try:
        segments = json.loads(segments_json)
    except (TypeError, ValueError):
        return ""
    if not isinstance(segments, list):
        return ""
    text = " ".join(
        str(s.get("text", "") or "") for s in segments if isinstance(s, dict)
    )
    return text[:MAX_CHARS_PER_DOC]


def keywords(db: Session, docs: list[Document]) -> list[dict]:
    """TF-IDF over the channel's cached transcripts: each term's tf-idf
    summed across documents, top ``TOP_KEYWORDS``, weights relative to the
    top term. Newest ``MAX_KEYWORD_DOCS`` documents only."""
    ordered = sorted(
        docs,
        key=lambda d: d.published_at or d.created_at or datetime.min,
        reverse=True,
    )[:MAX_KEYWORD_DOCS]
    ids = [d.document_id for d in ordered]
    if not ids:
        return []
    texts = [
        _transcript_text(row.segments_json)
        for row in db.query(TranscriptCache.segments_json).filter(
            TranscriptCache.document_id.in_(ids)
        )
    ]
    texts = [t for t in texts if t.strip()]
    if not texts:
        return []

    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(
        stop_words=sorted(FUNCTION_WORDS | TRANSCRIPT_FILLER),
        token_pattern=TOKEN_PATTERN,
        lowercase=True,
        sublinear_tf=True,
        min_df=2 if len(texts) >= 5 else 1,
        max_features=20_000,
    )
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        # Every token was a stop word or the vocabulary is empty.
        return []
    terms = vectorizer.get_feature_names_out()
    scores = matrix.sum(axis=0).A1
    doc_freq = (matrix > 0).sum(axis=0).A1
    top = scores.argsort()[::-1][:TOP_KEYWORDS]
    if len(top) == 0 or scores[top[0]] <= 0:
        return []
    peak = float(scores[top[0]])
    return [
        {
            "term": str(terms[i]),
            "weight": round(float(scores[i]) / peak, 4),
            "documents": int(doc_freq[i]),
        }
        for i in top
        if scores[i] > 0
    ]


def stance(docs: list[Document]) -> dict | None:
    """Monthly stance and sentiment counts where social classification
    exists (D-014). None when no document carries it."""
    by_stance: dict[str, Counter] = defaultdict(Counter)
    by_sentiment: dict[str, Counter] = defaultdict(Counter)
    classified = 0
    for d in docs:
        if not d.source_metadata_json or not d.published_at:
            continue
        try:
            meta = json.loads(d.source_metadata_json)
        except (TypeError, ValueError):
            continue
        cls = meta.get("classification") if isinstance(meta, dict) else None
        if not isinstance(cls, dict):
            continue
        month = _month(d.published_at)
        if cls.get("stance"):
            by_stance[month][str(cls["stance"])] += 1
        if cls.get("sentiment"):
            by_sentiment[month][str(cls["sentiment"])] += 1
        classified += 1
    if not classified:
        return None
    return {
        "stance": [{"month": m, "counts": dict(c)} for m, c in sorted(by_stance.items())],
        "sentiment": [{"month": m, "counts": dict(c)} for m, c in sorted(by_sentiment.items())],
        "classified_documents": classified,
    }


def document_aggregate(db: Session, docs: list[Document], transcripts: dict[str, str]) -> dict:
    with_knowledge = sum(1 for d in docs if d.extracted_knowledge_json)
    total = len(docs)
    notes: dict[str, str] = {}
    topics = label_counts(docs, "topics")
    concepts = label_counts(docs, "concepts")
    cloud = keywords(db, docs)
    stance_part = stance(docs)

    if total == 0:
        notes["documents"] = "Nothing from this channel is on your shelf yet."
    if total and not with_knowledge:
        notes["topics"] = (
            f"Topics and concepts come from knowledge reports. None of this channel's "
            f"{total} {'document has' if total == 1 else 'documents have'} one yet."
        )
    elif total and with_knowledge < total:
        missing = total - with_knowledge
        notes["topics"] = (
            f"Built from {with_knowledge} of {total} documents. Extract knowledge for "
            f"{missing} more to fill these in."
        )
    if total and not cloud:
        notes["keywords"] = "No transcripts are cached for this channel's documents yet."
    if total and stance_part is None:
        notes["stance"] = (
            "Stance and sentiment are classified only for social posts (Reddit, Hacker News, "
            "Mastodon, Bluesky, podcasts); this channel's documents carry none."
        )

    return {
        "coverage": {
            "documents": total,
            "with_knowledge": with_knowledge,
            "without_knowledge": total - with_knowledge,
            "ratio": round(with_knowledge / total, 4) if total else 0.0,
            "with_transcript": len(transcripts),
            "extractable": [
                _ref(d)
                for d in sorted(
                    docs,
                    key=lambda x: x.published_at or x.created_at or datetime.min,
                    reverse=True,
                )
                if not d.extracted_knowledge_json and d.document_id in transcripts
            ],
        },
        "cadence": cadence(docs),
        "durations": durations(docs),
        "topics": topics,
        "concepts": concepts,
        "keywords": cloud,
        "stance": stance_part,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Q&A activity (live, never cached)
# ---------------------------------------------------------------------------

def _video_id_from_url(url: str) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.netloc or "").lower()
    if host.endswith("youtu.be"):
        return parsed.path.strip("/").split("/")[0] or None
    if "youtube" in host:
        values = parse_qs(parsed.query).get("v")
        return values[0] if values else None
    return None


def _cited_video_ids(references_json: str | None) -> set[str]:
    try:
        refs = json.loads(references_json or "[]")
    except (TypeError, ValueError):
        return set()
    out: set[str] = set()
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, dict):
            continue
        if (ref.get("source_type") or "video") != "video":
            continue
        vid = ref.get("video_id") or _video_id_from_url(ref.get("youtube_link") or "") or _video_id_from_url(ref.get("video_url") or "")
        if vid:
            out.add(vid)
    return out


def qa_activity(db: Session, tenant_id: str, docs: list[Document]) -> dict:
    """The tenant's own exchanges (job and library Q&A) that cite at least
    one of the channel's visible documents."""
    by_video = {d.video_id: d for d in docs if d.video_id}
    if not by_video:
        return {"exchanges": 0, "most_cited": [], "recent": []}

    rows: list[tuple[str, str, str, datetime | None, str | None, str | None]] = []
    for ex in (
        db.query(QAExchange)
        .filter(QAExchange.tenant_id == tenant_id)
        .order_by(QAExchange.created_at.desc())
        .limit(MAX_EXCHANGES_SCANNED)
    ):
        rows.append(("job", ex.id, ex.question, ex.created_at, ex.job_id, ex.references))
    for ex in (
        db.query(LibraryQAExchange)
        .filter(LibraryQAExchange.tenant_id == tenant_id)
        .order_by(LibraryQAExchange.created_at.desc())
        .limit(MAX_EXCHANGES_SCANNED)
    ):
        rows.append(("library", ex.id, ex.question, ex.created_at, None, ex.references_json))

    citing: list[dict] = []
    cited_counts: Counter = Counter()
    for kind, ex_id, question, created_at, job_id, refs in rows:
        hits = _cited_video_ids(refs) & by_video.keys()
        if not hits:
            continue
        citing.append(
            {"id": ex_id, "kind": kind, "question": question, "created_at": created_at, "job_id": job_id}
        )
        cited_counts.update(hits)

    def _ts(item: dict) -> datetime:
        value = item["created_at"]
        if value is None:
            return datetime.min
        return value.replace(tzinfo=None) if value.tzinfo else value

    citing.sort(key=_ts, reverse=True)
    most_cited = [
        {
            "label": by_video[vid].title,
            "documents": n,
            "examples": [_ref(by_video[vid])],
        }
        for vid, n in cited_counts.most_common(10)
    ]
    return {"exchanges": len(citing), "most_cited": most_cited, "recent": citing[:RECENT_EXCHANGES]}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def get_intelligence(db: Session, tenant_id: str, channel: Channel, *, refresh: bool = False) -> dict:
    docs = visible_channel_documents(db, tenant_id, channel.channel_id)
    transcripts = _transcript_states(db, [d.document_id for d in docs])
    fp = fingerprint(docs, transcripts)

    row = (
        db.query(ChannelIntelligenceCache)
        .filter(
            ChannelIntelligenceCache.channel_id == channel.channel_id,
            ChannelIntelligenceCache.tenant_id == tenant_id,
        )
        .first()
    )
    cached = row is not None and not refresh and row.fingerprint == fp
    if cached:
        payload = json.loads(row.payload_json)
        computed_at = row.computed_at
        if computed_at.tzinfo is None:  # SQLite hands back naive UTC
            computed_at = computed_at.replace(tzinfo=timezone.utc)
    else:
        payload = document_aggregate(db, docs, transcripts)
        computed_at = datetime.now(timezone.utc)
        if row is None:
            row = ChannelIntelligenceCache(channel_id=channel.channel_id, tenant_id=tenant_id)
            db.add(row)
        row.fingerprint = fp
        row.computed_at = computed_at
        row.payload_json = json.dumps(payload)
        db.commit()
        logger.info(
            "channel intelligence: computed %s for tenant %s over %d documents",
            channel.channel_id, tenant_id[:8], len(docs),
        )

    return {
        **payload,
        "channel_id": channel.channel_id,
        "computed_at": computed_at,
        "cached": cached,
        "qa": qa_activity(db, tenant_id, docs),
    }
