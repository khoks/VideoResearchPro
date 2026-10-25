"""Dataset export helpers for fine-tune JSONL files.

Provides row iterators over the Q&A-family tables and the knowledge-enriched
documents the tenant can see, plus both-format serializers (OpenAI chat
`messages` and plain `{system, user, assistant}` tuple). All generators yield
one JSON-serialized line at a time so the HTTP layer can stream with constant
memory.
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
from app.models.qa_history_exchange import QAHistoryExchange
from app.models.document import Document
from app.services import visibility_service

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


def iter_qa_rows(db: Session, tenant_id: str) -> Iterator[tuple[str, str]]:
    """Yield ``(question, answer)`` pairs across every Q&A source, for ONE tenant.

    S-5.7.1: this previously unioned all three tables unfiltered, so any
    authenticated user could download every other user's questions and answers
    as fine-tune data — the highest-severity leak in the audit.

    Sources: ``qa_exchanges`` (job-scoped), ``library_qa_exchanges``
    (library-scoped), and ``qa_history_exchanges`` (history-chat).

    Rows are ordered by ``created_at ASC`` via a UNION ALL subquery so the DB
    does a single sorted scan. Streaming uses ``yield_per`` to keep memory
    O(batch) even on huge result sets.
    """
    selects = [
        db.query(
            QAExchange.created_at.label("created_at"),
            QAExchange.question.label("question"),
            QAExchange.answer.label("answer"),
        ).filter(QAExchange.tenant_id == tenant_id).statement,
        db.query(
            LibraryQAExchange.created_at.label("created_at"),
            LibraryQAExchange.question.label("question"),
            LibraryQAExchange.answer.label("answer"),
        ).filter(LibraryQAExchange.tenant_id == tenant_id).statement,
        db.query(
            QAHistoryExchange.created_at.label("created_at"),
            QAHistoryExchange.question.label("question"),
            QAHistoryExchange.answer.label("answer"),
        ).filter(QAHistoryExchange.tenant_id == tenant_id).statement,
    ]

    stmt = union_all(*selects).order_by("created_at")
    result = db.execute(stmt, execution_options={"yield_per": _YIELD_PER})
    for row in result:
        # SQLAlchemy 2.x Row supports index access; positions match the SELECT list.
        yield row[1], row[2]


def iter_knowledge_rows(
    db: Session, tenant_id: str
) -> Iterator[tuple[list[str], list[str], list[str], str]]:
    """Yield ``(topics, concepts, events, knowledge_report_md)`` for the
    documents THIS tenant can see.

    S-5.7.1: `documents` is the shared global cache and carries no tenant of
    its own. Without a tenant filter the export shipped every user's
    knowledge artifacts to anyone who asked.

    S-5.10.5: the filter is the tenant's visibility grants, keyed on
    ``document_id`` (D-063, D-070) — the same set the library lists and
    library Q&A retrieves from. It used to derive ownership from the jobs
    that selected the document, joined on the legacy ``video_id``, so a
    document with no job (a pasted URL, an uploaded PDF), one whose job the
    user deleted (deleting a job keeps its documents in the library), and
    every non-video document (``video_id`` is NULL) never exported.

    Selects the three columns it needs, not ``Document`` entities, and sets
    ``Query.yield_per``. The entity query raised as soon as one row matched:
    the legacy ``Query`` uniquifies the rows of any entity query unless
    ``Query.yield_per()`` set its load option, ``execution_options(yield_per=
    ...)`` sets only the execution option, and SQLAlchemy refuses
    ``yield_per`` with ``unique()`` (2.0 and 2.1 alike), so the stream broke
    on its first record. Either change alone fixes
    it; the column select also skips the eager ``Document.channel`` join and
    the unused columns. Every test before S-5.10.5 either stubbed this
    function or matched no row.
    """
    q = (
        db.query(
            Document.document_id,
            Document.extracted_knowledge_json,
            Document.knowledge_report_md,
        )
        .filter(
            Document.knowledge_report_md.isnot(None),
            Document.document_id.in_(visibility_service.visible_document_ids(db, tenant_id)),
        )
        .order_by(Document.created_at.asc())
        .yield_per(_YIELD_PER)
    )
    for document_id, knowledge_json, report_md in q:
        topics: list[str] = []
        concepts: list[str] = []
        events: list[str] = []
        if knowledge_json:
            try:
                data = json.loads(knowledge_json)
                topics = list(data.get("topics") or [])
                concepts = list(data.get("concepts") or [])
                events = list(data.get("events") or [])
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning(
                    "Failed to parse extracted_knowledge_json for document_id=%s",
                    document_id,
                )
        yield topics, concepts, events, report_md or ""


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


def _iter_qa_triples(db: Session, tenant_id: str) -> Iterator[tuple[str, str, str]]:
    for question, answer in iter_qa_rows(db, tenant_id):
        yield QA_SYSTEM_PROMPT, question, answer


def _iter_knowledge_triples(db: Session, tenant_id: str) -> Iterator[tuple[str, str, str]]:
    for topics, concepts, events, report in iter_knowledge_rows(db, tenant_id):
        yield KNOWLEDGE_SYSTEM_PROMPT, _knowledge_user_prompt(topics, concepts, events), report


def stream_qa_openai(db: Session, tenant_id: str) -> Iterator[str]:
    for sys_, user, assistant in _iter_qa_triples(db, tenant_id):
        yield serialize_openai_chat(sys_, user, assistant)


def stream_qa_tuple(db: Session, tenant_id: str) -> Iterator[str]:
    for sys_, user, assistant in _iter_qa_triples(db, tenant_id):
        yield serialize_tuple(sys_, user, assistant)


def stream_knowledge_openai(db: Session, tenant_id: str) -> Iterator[str]:
    for sys_, user, assistant in _iter_knowledge_triples(db, tenant_id):
        yield serialize_openai_chat(sys_, user, assistant)


def stream_knowledge_tuple(db: Session, tenant_id: str) -> Iterator[str]:
    for sys_, user, assistant in _iter_knowledge_triples(db, tenant_id):
        yield serialize_tuple(sys_, user, assistant)
