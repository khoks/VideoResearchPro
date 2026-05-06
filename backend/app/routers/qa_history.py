"""Q&A history chat router (Unit 2 — Personal Wiki).

Endpoints:
    POST /api/v1/qa-history/chat       Ask a meta-question across every Q&A
                                        the user has ever had. Runs the
                                        history agent, persists the turn,
                                        and upserts the new exchange into
                                        ``qa_library_global`` so future
                                        history queries see it.
    GET  /api/v1/qa-history/exchanges  List persisted history chat
                                        exchanges, oldest-first (job
                                        convention).
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.qa_history_exchange import QAHistoryExchange
from app.schemas.qa_history import (
    QAHistoryChatRequest,
    QAHistoryChatResponse,
    QAHistoryReference,
)
from app.services import chroma_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/qa-history",
    tags=["qa-history"],
    dependencies=[Depends(get_current_user)],
)


def _index_exchange_in_qa_library(exchange: QAHistoryExchange) -> None:
    """Best-effort upsert of the new history exchange into ``qa_library_global``.

    If Unit 1 hasn't landed yet (``upsert_qa_exchange`` missing) or the
    upsert fails for any reason, log and continue — never block the
    response on the Chroma side effect.
    """
    try:
        upsert = getattr(chroma_service, "upsert_qa_exchange", None)
        if upsert is None:
            logger.info(
                "chroma_service.upsert_qa_exchange not available yet "
                "(Unit 1 pending); skipping Q&A library indexing for "
                "exchange id=%s",
                exchange.id,
            )
            return
        upsert(exchange, source="history")
    except Exception:
        logger.exception(
            "Failed to upsert Q&A history exchange id=%s into qa_library_global",
            exchange.id,
        )


def _parse_references(exchange: QAHistoryExchange) -> list[QAHistoryReference]:
    try:
        raw = json.loads(exchange.references_json or "[]")
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning(
            "Failed to parse references_json for qa_history_exchange id=%s",
            exchange.id,
        )
        return []
    refs: list[QAHistoryReference] = []
    for item in raw:
        try:
            refs.append(QAHistoryReference(**item))
        except Exception:
            logger.warning(
                "Skipping malformed reference in qa_history_exchange id=%s",
                exchange.id,
            )
    return refs


@router.post(
    "/chat",
    response_model=QAHistoryChatResponse,
)
async def ask_qa_history(
    request: QAHistoryChatRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> QAHistoryChatResponse:
    """Run the Q&A history agent, persist the exchange, index it."""
    # Lazy import so tests can patch ``app.routers.qa_history.run_qa_history_chat_agent``.
    from app.agents.qa_history_agent import run_qa_history_chat_agent

    result = await run_qa_history_chat_agent(
        question=request.question,
        answer_language=request.answer_language,
        tenant_id=current_user.id,
    )
    answer = result.get("answer", "")
    references = result.get("references", []) or []

    # Per E-5.1 phase 2a, stamp tenant_id from the authenticated user.
    exchange = QAHistoryExchange(
        question=request.question,
        answer=answer,
        references_json=json.dumps(references),
        answer_language=request.answer_language,
        tenant_id=current_user.id,
    )
    db.add(exchange)
    db.commit()
    db.refresh(exchange)

    # Best-effort: add the new exchange to qa_library_global so tomorrow's
    # meta-questions can reference today's meta-answers.
    _index_exchange_in_qa_library(exchange)

    return QAHistoryChatResponse(
        id=exchange.id,
        question=exchange.question,
        answer=exchange.answer,
        references=[QAHistoryReference(**r) for r in references],
        answer_language=exchange.answer_language,
        created_at=exchange.created_at,
    )


@router.get(
    "/exchanges",
    response_model=list[QAHistoryChatResponse],
)
def list_qa_history(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[QAHistoryChatResponse]:
    """Return history chat exchanges ordered by ``created_at`` ASC.

    Per E-5.1 phase 2b, filtered to the authenticated user's tenant.
    """
    exchanges = (
        db.query(QAHistoryExchange)
        .filter(QAHistoryExchange.tenant_id == current_user.id)
        .order_by(QAHistoryExchange.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        QAHistoryChatResponse(
            id=qa.id,
            question=qa.question,
            answer=qa.answer,
            references=_parse_references(qa),
            answer_language=qa.answer_language,
            created_at=qa.created_at,
        )
        for qa in exchanges
    ]
