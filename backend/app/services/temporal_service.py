"""Discussed-era extraction and helpers — R3 / S-1.17.2.

THE DISTINCTION THIS MODULE EXISTS FOR
--------------------------------------
Every document carries `published_at`: when it was posted. That reached the
prompts in D-066. What it does NOT say is which period the source is ABOUT.
A 2026 video walking through a 2019 paper is a 2026 source about a 2019
event; a 2024 lecture on the Mughal empire discusses the sixteenth century.
Ranking, extraction, Q&A and the report all need both dates, and until now
they had one.

The extracted shape, persisted on `documents.discussed_era_json`::

    {"era_start": 2019, "era_end": 2021, "era_confidence": 0.8,
     "is_retrospective": true, "era_label": "...",
     "extracted_at": "...", "model": "..."}

Years are integers (negative = BCE) so Chroma can range-filter on them.
``None`` years mean "undatable" — a how-to with no dated referents — and are
distinct from "not extracted yet" (the column is NULL). Both read as UNKNOWN
downstream; neither is ever interpreted as "discusses now".

COST AND FAILURE SHAPE
----------------------
One economy-tier call per document, the first time any job chunks it, then
reused forever (same compute-once rule as transcripts and embeddings,
D-063). ~5K tokens in, ~80 out, reasoning OFF. Every failure is fail-soft:
the document keeps a NULL era and the job continues — an era is enrichment
on top of a working pipeline, never a dependency of it. Failures are NOT
persisted, so a transient outage is retried by the next job that touches
the document rather than freezing it as unknown forever.

EXISTING CHUNKS
---------------
Chunks embedded before this shipped carry no era (and no numeric publish
fields). They are treated as UNKNOWN; there is no Chroma backfill. A
document gains its era the next time a job re-chunks it, and its NEW chunks
carry it; the old ones in Chroma do not. This is deliberate: a backfill
would re-embed the whole library for a metadata field that only ranking and
filtering read, and "unknown" is the honest value for a chunk nobody has
dated.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import tiktoken

from app.agents.prompts.temporal_prompts import TEMPORAL_SCOPE_PROMPT
from app.config import settings

logger = logging.getLogger(__name__)

ERA_KEYS: tuple[str, ...] = ("era_start", "era_end", "era_confidence", "is_retrospective")

# Strict JSON of ~80 tokens. Reasoning is OFF for this use case, so the whole
# budget is visible output (the D-052 trap: on reasoning models the budget
# includes thinking tokens and a small cap yields an empty completion).
MAX_COMPLETION_TOKENS = 400

# Eras below this confidence are shown with a caveat; eras at zero
# confidence are treated as unknown.
LOW_CONFIDENCE = 0.4

_SQL_IN_CHUNK = 500


class _EraRow:
    """Duck-typed holder so `load_era` can read a bare JSON column value."""

    def __init__(self, raw: Any) -> None:
        self.discussed_era_json = raw


def sample_transcript(segments_or_text: Any, window_tokens: int | None = None) -> str:
    """Opening / middle / closing windows of a transcript, joined with "[...]".

    The opening almost always names the subject; the middle and close catch a
    source that pivots half-way. Three bounded windows keep the call at ~5K
    tokens whatever the transcript length.
    """
    if isinstance(segments_or_text, str):
        text = segments_or_text
    else:
        parts: list[str] = []
        for seg in segments_or_text or []:
            t = seg.get("text") if isinstance(seg, dict) else str(seg)
            if t and str(t).strip():
                parts.append(str(t).strip())
        text = " ".join(parts)
    text = text.strip()
    if not text:
        return ""

    window = int(window_tokens or settings.TEMPORAL_SCOPE_WINDOW_TOKENS)
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(text)
        if len(tokens) <= window * 3:
            return text
        mid = len(tokens) // 2 - window // 2
        windows = [
            enc.decode(tokens[:window]),
            enc.decode(tokens[mid:mid + window]),
            enc.decode(tokens[-window:]),
        ]
        return "\n[...]\n".join(w.strip() for w in windows)
    except Exception:
        chars = window * 4
        if len(text) <= chars * 3:
            return text
        mid = len(text) // 2 - chars // 2
        return "\n[...]\n".join([text[:chars], text[mid:mid + chars], text[-chars:]])


def _coerce_year(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_era_payload(raw: str) -> dict | None:
    """Validate the model's JSON into the persisted shape, or None.

    Tolerates code fences and prose around the object. Rejects anything that
    is not an object with the four required keys; a swapped start/end is
    corrected rather than rejected, a lone bound becomes a point era.
    """
    content = (raw or "").strip()
    if content.startswith("```"):
        lines = content.splitlines()
        end = -1 if lines and lines[-1].startswith("```") else len(lines)
        content = "\n".join(lines[1:end]).strip()
    if not content.startswith("{"):
        start_i, end_i = content.find("{"), content.rfind("}")
        if start_i < 0 or end_i < start_i:
            return None
        content = content[start_i:end_i + 1]
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or any(k not in data for k in ERA_KEYS):
        return None

    start = _coerce_year(data.get("era_start"))
    end = _coerce_year(data.get("era_end"))
    if (start is None) != (end is None):
        start = end = start if start is not None else end
    if start is not None and end is not None and start > end:
        start, end = end, start

    try:
        confidence = float(data.get("era_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    if start is None:
        confidence = 0.0

    label = data.get("era_label")
    label = (
        str(label).strip()[:80]
        if isinstance(label, (str, int, float)) and str(label).strip()
        else ""
    )

    return {
        "era_start": start,
        "era_end": end,
        "era_confidence": round(confidence, 2),
        "is_retrospective": bool(data.get("is_retrospective")),
        "era_label": label,
    }


def published_display(published_at: Any) -> str:
    """`YYYY-MM-DD` for a datetime or ISO string; "" when unknown."""
    if not published_at:
        return ""
    if hasattr(published_at, "isoformat"):
        return published_at.isoformat()[:10]
    return str(published_at)[:10]


def extract_discussed_era(
    title: str,
    description: str | None,
    published_at: Any,
    segments_or_text: Any,
    llm: Any | None = None,
) -> dict | None:
    """Run the `temporal_scope_extract` use case once. None on any failure."""
    samples = sample_transcript(segments_or_text)
    if not samples:
        return None

    from app.services.llm_routing import resolve_config
    from app.services.llm_service import get_llm_for, response_text

    prompt = TEMPORAL_SCOPE_PROMPT.format(
        title=(title or "").strip() or "Unknown",
        published_at=published_display(published_at) or "unknown",
        description=(description or "").strip()[:1500] or "(none)",
        samples=samples,
    )
    try:
        from langchain_core.messages import HumanMessage

        client = llm or get_llm_for(
            "temporal_scope_extract", temperature=0.0, max_tokens=MAX_COMPLETION_TOKENS
        )
        response = client.invoke([HumanMessage(content=prompt)])
        era = parse_era_payload(response_text(response))
    except Exception:
        logger.exception("temporal_scope_extract failed for %r", title)
        return None
    if era is None:
        logger.warning("temporal_scope_extract returned unparseable JSON for %r", title)
        return None
    era["extracted_at"] = datetime.now(timezone.utc).isoformat()
    try:
        era["model"] = resolve_config("temporal_scope_extract").model
    except Exception:
        era["model"] = ""
    return era


def load_era(document: Any) -> dict | None:
    """Parse a document's persisted era. None when missing or malformed."""
    raw = getattr(document, "discussed_era_json", None)
    if not raw:
        return None
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(data, dict) or any(k not in data for k in ERA_KEYS):
        return None
    return data


def is_known(era: dict | None) -> bool:
    """An era counts as known when it has a start year and non-zero confidence."""
    return bool(era) and era.get("era_start") is not None and (era.get("era_confidence") or 0) > 0


def ensure_discussed_era(db: Any, document: Any, segments_or_text: Any) -> dict | None:
    """Return the document's era, extracting and persisting it on first use.

    Fail-soft by contract: returns None (unknown) on any error and never
    raises into the job loop. Failures are not persisted — see the module
    docstring for why.
    """
    existing = load_era(document)
    if existing is not None:
        return existing
    if not settings.TEMPORAL_SCOPE_ENABLED:
        return None
    if getattr(document, "discussed_era_json", None):
        # Present but malformed: do not burn a call every job on a row we
        # cannot read; treat as unknown.
        return None

    era = extract_discussed_era(
        getattr(document, "title", "") or "",
        getattr(document, "description", None),
        getattr(document, "published_at", None),
        segments_or_text,
    )
    if era is None:
        return None
    try:
        document.discussed_era_json = json.dumps(era, ensure_ascii=False)
        if db is not None:
            db.commit()
    except Exception:
        logger.exception(
            "Could not persist discussed era for document %s",
            getattr(document, "video_id", "?"),
        )
        try:
            if db is not None:
                db.rollback()
        except Exception:
            pass
    return era


def format_year(year: int | None) -> str:
    if year is None:
        return "?"
    return f"{abs(int(year))} BCE" if int(year) < 0 else str(int(year))


def era_span_text(era: dict | None) -> str:
    """"2019–2021", "2024", "500 BCE–200" or "" when unknown."""
    if not is_known(era):
        return ""
    start, end = era.get("era_start"), era.get("era_end")
    if end is None or end == start:
        return format_year(start)
    return f"{format_year(start)}–{format_year(end)}"


def era_for_prompt(era: dict | None) -> str:
    """One short clause for a prompt line, or "" when nothing is known.

    e.g. "discusses 2019–2021 (retrospective)" or
    "discusses 2024 (low confidence)".
    """
    span = era_span_text(era)
    if not span:
        return ""
    notes: list[str] = []
    if era.get("is_retrospective"):
        notes.append("retrospective")
    if (era.get("era_confidence") or 0) < LOW_CONFIDENCE:
        notes.append("low confidence")
    suffix = f" ({', '.join(notes)})" if notes else ""
    return f"discusses {span}{suffix}"


def era_from_chunk_metadata(meta: dict | None) -> dict | None:
    """Inverse of `era_metadata`: rebuild an era dict from a chunk's flat
    metadata, or None when the chunk carries no era (pre-R3 chunks)."""
    meta = meta or {}
    if meta.get("era_start") is None:
        return None
    return {
        "era_start": meta.get("era_start"),
        "era_end": meta.get("era_end"),
        "era_confidence": meta.get("era_confidence", 1.0),
        "is_retrospective": bool(meta.get("is_retrospective", False)),
    }


def era_metadata(era: dict | None) -> dict:
    """Flat scalar fields for chunk metadata. EMPTY when the era is unknown.

    Keys are omitted rather than written as sentinels so a Chroma range
    filter on `era_start` naturally excludes undated chunks instead of
    matching them against a fake year.
    """
    if not is_known(era):
        return {}
    end = era.get("era_end")
    return {
        "era_start": int(era["era_start"]),
        "era_end": int(end if end is not None else era["era_start"]),
        "era_confidence": float(era.get("era_confidence") or 0.0),
        "is_retrospective": bool(era.get("is_retrospective")),
    }


def summarize_eras(eras: Iterable[dict | None]) -> dict:
    """Corpus-level era summary for `compute_statistics` and the Q&A note."""
    known = [e for e in eras if is_known(e)]
    if not known:
        return {
            "era_known_count": 0,
            "discussed_era_start": None,
            "discussed_era_end": None,
            "retrospective_count": 0,
        }
    starts = [int(e["era_start"]) for e in known]
    ends = [
        int(e["era_end"]) if e.get("era_end") is not None else int(e["era_start"])
        for e in known
    ]
    return {
        "era_known_count": len(known),
        "discussed_era_start": min(starts),
        "discussed_era_end": max(ends),
        "retrospective_count": sum(1 for e in known if e.get("is_retrospective")),
    }


def describe_corpus_eras(statistics: dict | None) -> str:
    """Prose fragment from `summarize_eras` output, or "" when nothing known."""
    stats = statistics or {}
    known = int(stats.get("era_known_count") or 0)
    if not known or stats.get("discussed_era_start") is None:
        return ""
    span = era_span_text({
        "era_start": stats.get("discussed_era_start"),
        "era_end": stats.get("discussed_era_end"),
        "era_confidence": 1.0,
    })
    retro = int(stats.get("retrospective_count") or 0)
    text = f"the subject matter spans {span} ({known} source(s) dated by content"
    if retro:
        text += f", {retro} of them retrospective"
    return text + ")"


def known_eras_for(db: Any, video_ids: Iterable[str]) -> dict[str, dict]:
    """Persisted eras for documents already in the library, keyed by video_id.

    Used by search ranking: a candidate the library has seen before carries
    its discussed era into the ranking prompt; unseen candidates carry none
    and the model works from title and description alone.
    """
    from app.models.document import Document

    ids = sorted({v for v in video_ids if v})
    if not ids or db is None:
        return {}
    out: dict[str, dict] = {}
    for i in range(0, len(ids), _SQL_IN_CHUNK):
        rows = (
            db.query(Document.video_id, Document.discussed_era_json)
            .filter(Document.video_id.in_(ids[i:i + _SQL_IN_CHUNK]))
            .filter(Document.discussed_era_json.isnot(None))
            .all()
        )
        for vid, raw in rows:
            era = load_era(_EraRow(raw))
            if is_known(era):
                out[vid] = era
    return out
