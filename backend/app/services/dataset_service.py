"""Dataset export helpers for fine-tune JSONL files.

Provides row iterators over the Q&A-family tables and the knowledge-enriched
videos table, plus both-format serializers (OpenAI chat `messages` and plain
`{system, user, assistant}` tuple). All generators yield one JSON-serialized
line at a time so the HTTP layer can stream with constant memory.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from sqlalchemy import union_all
from sqlalchemy.orm import Session

from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange

logger = logging.getLogger(__name__)

# Verbatim per plan — DO NOT edit these strings; they are the shipped fine-tune
# system prompts and must match what users train against.
QA_SYSTEM_PROMPT = (
    "You are a research assistant who can answer questions for the user. "
    "The user is going to ask a question. Try to answer that question."
)
KNOWLEDGE_SYSTEM_PROMPT = (
    "You are a knowledge assistant. You will be asked a question in which one "
    "or more topics, concepts, events or facts will be asked for. Generate a "
    "structured, report-style answer for it."
)

# Tune the DB fetch batch size. SQLite drivers ignore server-side cursors, but
# yield_per still bounds in-memory row buffering on the ORM side so we stay
# O(batch) even on huge result sets.
_YIELD_PER = 100


# ---------------------------------------------------------------------------
# Row iterators
# ---------------------------------------------------------------------------


def iter_qa_rows(db: Session) -> Iterator[tuple[str, str]]:
    """Yield ``(question, answer)`` pairs across every Q&A source.

    Sources: ``qa_exchanges`` (job-scoped), ``library_qa_exchanges``
    (library-scoped), and ``qa_history_exchanges`` (history-chat) when the
    model is available. The history-chat table ships in Unit 2; we import it
    lazily and skip gracefully if its module is not present so this service
    compiles without Unit 2 merged.

    Rows are ordered by ``created_at ASC`` via a UNION ALL subquery so the DB
    does a single sorted scan. Streaming uses ``yield_per`` to keep memory
    O(batch) even on huge result sets.
    """
    selects = [
        db.query(
            QAExchange.created_at.label("created_at"),
            QAExchange.question.label("question"),
            QAExchange.answer.label("answer"),
        ).statement,
        db.query(
            LibraryQAExchange.created_at.label("created_at"),
            LibraryQAExchange.question.label("question"),
            LibraryQAExchange.answer.label("answer"),
        ).statement,
    ]

    # TODO(unit-2): once `app.models.qa_history_exchange` lands, this import
    # becomes unconditional.
    try:
        from app.models.qa_history_exchange import QAHistoryExchange  # type: ignore

        selects.append(
            db.query(
                QAHistoryExchange.created_at.label("created_at"),
                QAHistoryExchange.question.label("question"),
                QAHistoryExchange.answer.label("answer"),
            ).statement
        )
    except ImportError:
        logger.debug("qa_history_exchange model not available; skipping that source")

    stmt = union_all(*selects).order_by("created_at")
    result = db.execute(stmt, execution_options={"yield_per": _YIELD_PER})
    for row in result:
        # SQLAlchemy 2.x Row supports index access; positions match the SELECT list.
        yield row[1], row[2]


def iter_knowledge_rows(db: Session) -> Iterator[tuple[list[str], list[str], list[str], str]]:
    """Yield ``(topics, concepts, events, knowledge_report_md)`` for every
    video with a populated knowledge report.

    The knowledge columns (``extracted_knowledge_json``, ``knowledge_report_md``)
    are added by Unit 4. If they are not present on the ``Video`` model yet we
    log once and yield nothing, which keeps the endpoint serving a valid
    (empty) JSONL body pre-merge instead of 500-ing.
    """
    # TODO(unit-4): remove the getattr guard once the columns are on the model.
    from app.models.video import Video

    if not hasattr(Video, "knowledge_report_md"):
        logger.info(
            "knowledge_report_md column not present on Video; knowledge export will be empty "
            "until Unit 4 ships"
        )
        return

    q = (
        db.query(Video)
        .filter(Video.knowledge_report_md.isnot(None))  # type: ignore[attr-defined]
        .order_by(Video.created_at.asc())
        .execution_options(yield_per=_YIELD_PER)
    )
    for video in q:
        raw_json = getattr(video, "extracted_knowledge_json", None)
        topics: list[str] = []
        concepts: list[str] = []
        events: list[str] = []
        if raw_json:
            try:
                data = json.loads(raw_json)
                topics = list(data.get("topics") or [])
                concepts = list(data.get("concepts") or [])
                events = list(data.get("events") or [])
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning(
                    "Failed to parse extracted_knowledge_json for video_id=%s",
                    video.video_id,
                )
        report = getattr(video, "knowledge_report_md", "") or ""
        yield topics, concepts, events, report


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _dumps(obj: dict[str, Any]) -> str:
    # ensure_ascii=False keeps non-English characters intact so the fine-tune
    # server doesn't see escaped garbage. json.dumps escapes embedded newlines
    # inside values, so appending "\n" below is safe.
    return json.dumps(obj, ensure_ascii=False)


def serialize_openai_chat(system: str, user: str, assistant: str) -> str:
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }
    return _dumps(payload) + "\n"


def serialize_tuple(system: str, user: str, assistant: str) -> str:
    payload = {"system": system, "user": user, "assistant": assistant}
    return _dumps(payload) + "\n"


# ---------------------------------------------------------------------------
# Composition helpers (what the router wires to StreamingResponse)
# ---------------------------------------------------------------------------


def _knowledge_user_prompt(topics: list[str], concepts: list[str], events: list[str]) -> str:
    # Spec: "Tell me about: {topics joined by ', '} (also related concepts: {concepts}, events: {events})"
    return (
        f"Tell me about: {', '.join(topics)} "
        f"(also related concepts: {', '.join(concepts)}, "
        f"events: {', '.join(events)})"
    )


def _iter_qa_triples(db: Session) -> Iterator[tuple[str, str, str]]:
    for question, answer in iter_qa_rows(db):
        yield QA_SYSTEM_PROMPT, question, answer


def _iter_knowledge_triples(db: Session) -> Iterator[tuple[str, str, str]]:
    for topics, concepts, events, report in iter_knowledge_rows(db):
        yield KNOWLEDGE_SYSTEM_PROMPT, _knowledge_user_prompt(topics, concepts, events), report


def stream_qa_openai(db: Session) -> Iterator[str]:
    for sys_, user, assistant in _iter_qa_triples(db):
        yield serialize_openai_chat(sys_, user, assistant)


def stream_qa_tuple(db: Session) -> Iterator[str]:
    for sys_, user, assistant in _iter_qa_triples(db):
        yield serialize_tuple(sys_, user, assistant)


def stream_knowledge_openai(db: Session) -> Iterator[str]:
    for sys_, user, assistant in _iter_knowledge_triples(db):
        yield serialize_openai_chat(sys_, user, assistant)


def stream_knowledge_tuple(db: Session) -> Iterator[str]:
    for sys_, user, assistant in _iter_knowledge_triples(db):
        yield serialize_tuple(sys_, user, assistant)
