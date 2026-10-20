"""Did a saved search's answer change? (S-8.3.3 / M3)

Plan: docs/plans/m3-saved-searches-alerts.md; thresholds pre-registered in
docs/notes/2026-10-19-saved-search-change-thresholds.md (#323) before any
value was computed. Three stages, cheapest first:

1. **Gate** (``scope_fingerprint``): a scheduled run whose scope resolves to
   the same document set as the last good run is skipped before the quota
   or the model, so cost follows ingest, not the number of searches. The
   set is compared, not visibility timestamps: a timestamp gate cannot see
   a shelf gaining a run whose documents were already visible, and on
   Windows a grant and a run can share a ~15 ms clock tick.
2. **Deterministic signals** (``compare``): the Jaccard overlap of the cited
   document sets (``J``) and the cosine distance between the two answers'
   embeddings (``D``), on the library's own MiniLM embedder. ``J`` below
   ``SAVED_SEARCH_JACCARD_THRESHOLD`` or ``D`` above
   ``SAVED_SEARCH_EMBEDDING_THRESHOLD`` is a vote for "changed". An answer
   hash cannot do this: the answering model is not deterministic.
3. **Judge only on disagreement**: when exactly one signal votes, one
   volume-tier call (``saved_search_judge``, reasoning off) decides and
   writes the sentence the notification shows. If the judge fails, the
   citation signal decides, because a changed source set is concrete.

The judge's prompt lives here, not under ``app/agents/prompts`` (that
package belongs to the report and Q&A agents). It reads two answers the
app wrote, already in English, so it carries the English-output contract
and not the transcript contracts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Callable

from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session

from app.agents.prompts.shared import ENGLISH_OUTPUT_CONTRACT
from app.config import settings
from app.services.llm_service import get_llm_for, response_text

logger = logging.getLogger(__name__)

JUDGE_USE_CASE = "saved_search_judge"
JUDGE_MAX_TOKENS = 400
#: Characters of each answer the judge sees (about 1,500 tokens each).
JUDGE_ANSWER_CHARS = 6000

JUDGE_PROMPT = """A researcher pinned a question. It was answered again from their own sources. Decide whether the new answer CHANGED in a way they would want to be told about.

{english}

QUESTION: {question}

PREVIOUS ANSWER:
{previous}

NEW ANSWER:
{current}

SOURCES: {sources}

Changed means the substance moved: a new claim, figure, event or source-backed finding; a reversal or a correction; a conclusion that no longer holds. Rewording, reordering, a different level of detail on the same points, or the same sources cited differently is NOT a change.

Return ONLY a JSON object, no prose and no code fences:
{{"changed": true or false, "what_changed": "one sentence of at most 30 words for the notification, naming the new point; empty when not changed"}}"""


@dataclass
class Verdict:
    """What the detector concluded about one run."""

    changed: bool | None
    jaccard: float | None = None
    distance: float | None = None
    #: none (first run, nothing to compare) | agreed | judged | judge_failed
    decided_by: str = "none"
    added: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    summary: str | None = None


# ---------------------------------------------------------------------------
# Stage 1


def scope_fingerprint(document_ids: list[str]) -> str:
    """sha256 of the sorted, de-duplicated document ids a run may cite."""
    return hashlib.sha256("\n".join(sorted(set(document_ids))).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Stage 2


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def cosine_distance(u: list[float], v: list[float]) -> float:
    dot = sum(x * y for x, y in zip(u, v))
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(y * y for y in v))
    return 1.0 - (dot / (nu * nv) if nu and nv else 0.0)


def _titles(refs: list[dict], keys: list[str]) -> list[str]:
    by_key: dict[str, str] = {}
    for r in refs:
        k = str(r.get("video_id") or "")
        if k and k not in by_key:
            by_key[k] = str(r.get("video_title") or k)
    return [by_key.get(k, k) for k in keys]


def _cited_summary(added_titles: list[str], dropped_titles: list[str]) -> str:
    def few(xs: list[str]) -> str:
        shown = ", ".join(f"“{t}”" for t in xs[:3])
        return shown + (f" and {len(xs) - 3} more" if len(xs) > 3 else "")

    parts = []
    if added_titles:
        parts.append(f"Now cites {len(added_titles)} new source{'s' if len(added_titles) != 1 else ''}: {few(added_titles)}.")
    if dropped_titles:
        parts.append(f"No longer cites {few(dropped_titles)}.")
    return " ".join(parts) or "The answer's wording moved substantially."


def _parse_judge(text: str) -> tuple[bool, str] | None:
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(body[start : end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("changed"), bool):
        return None
    what = data.get("what_changed")
    return data["changed"], (what.strip()[:400] if isinstance(what, str) else "")


def judge(
    *,
    question: str,
    previous_answer: str,
    current_answer: str,
    source_titles: list[str],
    tenant_id: str | None = None,
    db: Session | None = None,
) -> tuple[bool, str]:
    """One volume-tier call. Raises on a failed call or an unreadable reply."""
    prompt = JUDGE_PROMPT.format(
        english=ENGLISH_OUTPUT_CONTRACT,
        question=question,
        previous=(previous_answer or "")[:JUDGE_ANSWER_CHARS],
        current=(current_answer or "")[:JUDGE_ANSWER_CHARS],
        sources="; ".join(source_titles[:20]) or "(none cited)",
    )
    client = get_llm_for(JUDGE_USE_CASE, temperature=0.0, max_tokens=JUDGE_MAX_TOKENS, tenant_id=tenant_id, db=db)
    response = client.invoke([HumanMessage(content=prompt)])
    parsed = _parse_judge(response_text(response))
    if parsed is None:
        raise ValueError("judge reply was not the expected JSON")
    return parsed


def compare(
    *,
    question: str,
    previous_answer: str | None,
    previous_refs: list[dict],
    previous_embedding: list[float] | None,
    current_answer: str,
    current_refs: list[dict],
    current_embedding: list[float],
    judge_fn: Callable[..., tuple[bool, str]] | None = None,
    tenant_id: str | None = None,
    db: Session | None = None,
) -> Verdict:
    """Stages 2 and 3. With no previous answer the run is the baseline."""
    if previous_answer is None or previous_embedding is None:
        return Verdict(changed=None, decided_by="none")

    prev_keys = {str(r.get("video_id")) for r in previous_refs if r.get("video_id")}
    cur_keys = {str(r.get("video_id")) for r in current_refs if r.get("video_id")}
    added = sorted(cur_keys - prev_keys)
    dropped = sorted(prev_keys - cur_keys)
    j = jaccard(prev_keys, cur_keys)
    d = cosine_distance(previous_embedding, current_embedding)
    j_vote = j < settings.SAVED_SEARCH_JACCARD_THRESHOLD
    d_vote = d > settings.SAVED_SEARCH_EMBEDDING_THRESHOLD
    added_titles = _titles(current_refs, added)
    dropped_titles = _titles(previous_refs, dropped)

    v = Verdict(changed=None, jaccard=round(j, 4), distance=round(d, 4), added=added, dropped=dropped)
    if j_vote == d_vote:
        v.changed = j_vote
        v.decided_by = "agreed"
        v.summary = _cited_summary(added_titles, dropped_titles) if j_vote else None
        return v

    try:
        changed, what = (judge_fn or judge)(
            question=question,
            previous_answer=previous_answer,
            current_answer=current_answer,
            source_titles=_titles(current_refs, sorted(cur_keys)),
            tenant_id=tenant_id,
            db=db,
        )
        v.changed = changed
        v.decided_by = "judged"
        v.summary = (what or _cited_summary(added_titles, dropped_titles)) if changed else None
    except Exception:
        logger.exception("saved search judge failed; the citation signal decides")
        v.changed = j_vote
        v.decided_by = "judge_failed"
        v.summary = _cited_summary(added_titles, dropped_titles) if j_vote else None
    return v
