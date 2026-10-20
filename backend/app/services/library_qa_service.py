"""The library Q&A core, shared by every caller (T-8.3.3.6, filed by S-8.1.4).

``POST /library/qa``, ``POST /shelves/{id}/qa`` (``routers/library.py::
answer_library_question``) and a saved search's run
(``saved_search_service.execute``) all ask the library agent the same way:

1. ``prepare``: resolve the scope to the documents it may draw on (always
   inside the reader's visible set; ``[]`` retrieves nothing) and the notes
   it may draw on (every note for the whole library, a shelf's own notes for
   a shelf). Raises ``qa_scope_service.ScopeNotFound`` for a scope that is
   not the reader's, so a caller can 404 before checking any quota.
2. ``ask``: corpus statistics over that set, the reader's trust weights,
   the BYOK context, the agent, and, for a narrowed scope, the citation
   check that drops anything outside it.

Quota and persistence stay with each caller: the route raises 429 and
stores the exchange it answers with; a saved search records a skipped run
and stores its own exchange with a provenance key.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.document import Document
from app.services import qa_scope_service

logger = logging.getLogger(__name__)


@dataclass
class Prepared:
    """What a question over a scope may draw on."""

    scope: Any
    document_ids: list[str]
    #: ``None`` = every note of the reader (the whole library).
    note_keys: list[str] | None
    narrowed: bool


@dataclass
class Answer:
    answer: str
    references: list[dict]


def prepare(db: Session, tenant_id: str, scope) -> Prepared:
    document_ids = qa_scope_service.resolve_document_ids(db, tenant_id, scope)
    return Prepared(
        scope=scope,
        document_ids=document_ids,
        note_keys=qa_scope_service.note_target_keys(db, tenant_id, scope, document_ids),
        narrowed=bool(qa_scope_service.narrowing(scope)),
    )


def within_scope(
    db: Session,
    references: list[dict],
    document_ids: list[str],
    note_keys: list[str] | None = None,
) -> list[dict]:
    """Drop citations of documents outside a narrowed scope (S-8.1.4).

    Retrieval is already restricted to ``document_ids``; this is the check on
    what the answer cites, so a scoped answer can never point outside its
    scope even if a future context source does. A note citation (S-8.5.2)
    must target something in ``note_keys``. References that name neither a
    document nor a note are left alone.
    """
    allowed = set(document_ids)
    allowed_notes = set(note_keys or [])
    allowed_videos = (
        {
            row[0]
            for row in db.query(Document.video_id).filter(Document.document_id.in_(allowed))
            if row[0]
        }
        if allowed
        else set()
    )
    kept = []
    for ref in references:
        doc_id = ref.get("document_id") if isinstance(ref, dict) else None
        vid = ref.get("video_id") if isinstance(ref, dict) else None
        if isinstance(ref, dict) and ref.get("source_type") == "note":
            ok = f"{ref.get('note_target_type', '')}:{ref.get('note_target_id', '')}" in allowed_notes
        elif doc_id is not None:
            ok = doc_id in allowed
        elif vid is not None:
            ok = vid in allowed_videos
        else:
            ok = True
        if ok:
            kept.append(ref)
    if len(kept) != len(references):
        logger.warning(
            "Dropped %d citation(s) outside the question's scope", len(references) - len(kept)
        )
    return kept


def ask(
    db: Session,
    tenant_id: str,
    prepared: Prepared,
    *,
    question: str,
    answer_language: str = "en",
    output_length: str | None = None,
    agent: Callable[..., dict] | None = None,
) -> Answer:
    """Run the library agent over a prepared scope. ``agent`` is for tests;
    by default it is ``app.agents.qa_agent.run_library_qa_agent``, imported
    here at call time so tests that patch it there see the call."""
    from app.services import corpus_stats_service, llm_service, subscription_service

    if agent is None:
        from app.agents.qa_agent import run_library_qa_agent as agent  # noqa: N813

    # S-1.15.2: the same corpus-aware length policy as job Q&A, over the
    # scoped set.
    corpus_statistics = corpus_stats_service.corpus_statistics_for_document_ids(db, prepared.document_ids)
    # D-068 / S-7.1.1: THIS tenant's trust weights, resolved at request time.
    channel_weights = subscription_service.channel_weights(db, tenant_id)
    # T-5.6.4: BYOK context: Studio users' provider keys override the
    # install-wide keys for the duration of the call.
    with llm_service.byok_context(tenant_id, db):
        result = agent(
            question=question,
            answer_language=answer_language,
            visible_document_ids=prepared.document_ids,
            corpus_statistics=corpus_statistics,
            output_length=output_length,
            channel_weights=channel_weights,
            # S-8.5.2: the reader's notes join retrieval; a narrowed scope
            # draws only the notes on its own material.
            notes_tenant_id=tenant_id,
            note_target_keys=prepared.note_keys,
        )
    answer = result.get("answer", "") or ""
    references = result.get("references", []) or []
    if prepared.narrowed:
        references = within_scope(db, references, prepared.document_ids, prepared.note_keys)
    return Answer(answer=answer, references=references)
