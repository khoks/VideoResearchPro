"""The Celery worker's start hook (S-5.10.5, T-5.10.5.2).

``run_startup_backfills`` runs the API lifespan's two retrieval backfills
when a worker starts, so a worker-only start after an upgrade does not leave
chunks embedded before 2026-10-19 unretrievable (D-070). No worker is
started: the first test sends Celery's real ``worker_ready`` signal, which
is what the worker itself sends just before its consumer loop, so it proves
the hook is wired, not only that the function works. Both backfills are
patched; their own behaviour is tested in ``test_services``.
"""
from unittest.mock import MagicMock, call, patch

from celery.signals import worker_ready

from app.services import chroma_service
from app.tasks import celery_app as celery_app_module


def test_worker_ready_runs_both_backfills_in_the_api_order():
    backfills = MagicMock()
    with (
        patch.object(chroma_service, "backfill_qa_library", backfills.qa_library),
        patch.object(chroma_service, "backfill_chunk_document_ids", backfills.chunk_document_ids),
    ):
        responses = dict(worker_ready.send(sender=None))

    # Same order as app/main.py's lifespan; each once, with its defaults.
    assert backfills.mock_calls == [call.qa_library(), call.chunk_document_ids()]
    # Celery's Signal.send swallows a receiver's exception into its response,
    # so check the hook returned rather than raised.
    assert celery_app_module.run_startup_backfills in responses
    assert not isinstance(responses[celery_app_module.run_startup_backfills], Exception)


def test_a_failing_qa_backfill_still_runs_the_chunk_backfill():
    """Fail-soft like the API path: one backfill's failure is logged, never
    raised, and never skips the other."""
    with (
        patch.object(chroma_service, "backfill_qa_library", side_effect=RuntimeError("chroma down")),
        patch.object(chroma_service, "backfill_chunk_document_ids") as chunk_backfill,
        patch.object(celery_app_module, "logger") as logger,
    ):
        celery_app_module.run_startup_backfills()

    chunk_backfill.assert_called_once_with()
    logger.exception.assert_called_once()
    assert "Q&A library backfill failed" in logger.exception.call_args.args[0]


def test_a_failing_chunk_backfill_never_stops_the_worker():
    with (
        patch.object(chroma_service, "backfill_qa_library") as qa_backfill,
        patch.object(
            chroma_service, "backfill_chunk_document_ids", side_effect=RuntimeError("chroma down")
        ),
        patch.object(celery_app_module, "logger") as logger,
    ):
        celery_app_module.run_startup_backfills()

    qa_backfill.assert_called_once_with()
    logger.exception.assert_called_once()
    assert "Chunk document_id backfill failed" in logger.exception.call_args.args[0]
