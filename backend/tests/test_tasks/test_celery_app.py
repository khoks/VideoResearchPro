"""The Celery worker's start hooks (S-5.10.5, T-5.10.5.2).

``run_startup_backfills`` brings the API lifespan's two retrieval backfills
to the worker, so a worker-only start after an upgrade does not leave chunks
embedded before 2026-10-19 unretrievable (D-070). It stamps the chunks
before the consumer loop starts, then closes the Chroma client and drops the
embedding model, and queues the Q&A library backfill as a task instead of
running it inline. ``forget_inherited_chroma`` makes a forked pool child
build its own client and model instead of using its parent's.

No worker is started: the tests send Celery's real ``worker_ready`` and
``worker_process_init`` signals, which is what the worker and a prefork child
send, so they prove the hooks are wired, not only that the functions work.
The backfills themselves are patched; their behaviour is tested in
``test_services``. No real client or model is touched: the process state is
a set of stand-ins, restored after each test.
"""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from celery.signals import worker_process_init, worker_ready
from chromadb.api.shared_system_client import SharedSystemClient
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from app.services import chroma_service
from app.tasks import celery_app as celery_app_module


@pytest.fixture
def held(monkeypatch):
    """This process holds an open Chroma client and a loaded model, the state
    the worker's main process is in once the chunk backfill has opened the
    global collection."""
    client = MagicMock(name="chroma_client")
    embedding_function = MagicMock(name="embedding_function", model_name="the-model")
    model = object()
    system = object()
    monkeypatch.setattr(chroma_service, "_client", client)
    monkeypatch.setattr(chroma_service, "_embedding_function", embedding_function)
    monkeypatch.setattr(chroma_service, "_owner_pid", os.getpid())
    monkeypatch.setattr(chroma_service, "_inherited", [])
    # chromadb's own process-level caches: the loaded model is cached on the
    # embedding-function class and the System on SharedSystemClient, so
    # dropping our two references alone would leave both reachable.
    monkeypatch.setattr(SentenceTransformerEmbeddingFunction, "models", {"the-model": model})
    monkeypatch.setattr(SharedSystemClient, "_identifier_to_system", {"persist-dir": system})
    monkeypatch.setattr(SharedSystemClient, "_identifier_to_refcount", {"persist-dir": 1})
    return SimpleNamespace(client=client, embedding_function=embedding_function, model=model, system=system)


@pytest.fixture
def backfills(monkeypatch):
    stubs = SimpleNamespace(
        chunk_document_ids=MagicMock(name="backfill_chunk_document_ids", return_value=0),
        qa_library=MagicMock(name="backfill_qa_library", return_value=0),
        queued=MagicMock(name="backfill_qa_library_task"),
    )
    monkeypatch.setattr(chroma_service, "backfill_chunk_document_ids", stubs.chunk_document_ids)
    monkeypatch.setattr(chroma_service, "backfill_qa_library", stubs.qa_library)
    monkeypatch.setattr(celery_app_module, "backfill_qa_library_task", stubs.queued)
    return stubs


def _send_worker_ready():
    responses = dict(worker_ready.send(sender=None))
    # Celery's Signal.send swallows a receiver's exception into its response,
    # so check the hook returned rather than raised.
    assert celery_app_module.run_startup_backfills in responses
    assert not isinstance(responses[celery_app_module.run_startup_backfills], Exception)


def test_worker_ready_stamps_chunks_inline_and_queues_the_qa_backfill(held, backfills):
    """Only the chunk stamping gates retrieval, so only it runs before the
    consumer loop. The Q&A backfill re-embeds every exchange; it goes to the
    queue, where it never delays consumption and never embeds in the main
    process."""
    _send_worker_ready()

    backfills.chunk_document_ids.assert_called_once_with()
    backfills.qa_library.assert_not_called()
    backfills.queued.delay.assert_called_once_with()


def test_worker_ready_leaves_the_main_process_fork_clean(held, backfills):
    """A prefork pool forks every replacement child (after a revoke with
    terminate, a crash, an OOM kill) from the main process. After the hook it
    holds no open client and no model for a child to inherit."""
    _send_worker_ready()

    held.client.close.assert_called_once_with()
    assert chroma_service._client is None
    assert chroma_service._embedding_function is None
    assert chroma_service._owner_pid is None
    assert "the-model" not in SentenceTransformerEmbeddingFunction.models


def test_a_failing_chunk_backfill_still_releases_and_queues(held, backfills):
    backfills.chunk_document_ids.side_effect = RuntimeError("chroma down")
    with patch.object(celery_app_module, "logger") as logger:
        _send_worker_ready()

    logger.exception.assert_called_once()
    assert "Chunk document_id backfill failed" in logger.exception.call_args.args[0]
    held.client.close.assert_called_once_with()
    assert chroma_service._client is None
    backfills.queued.delay.assert_called_once_with()


def test_a_broker_failure_while_queueing_never_stops_the_worker(held, backfills):
    backfills.queued.delay.side_effect = ConnectionError("broker down")
    with patch.object(celery_app_module, "logger") as logger:
        _send_worker_ready()

    backfills.chunk_document_ids.assert_called_once_with()
    logger.exception.assert_called_once()
    assert "Could not queue the Q&A library backfill" in logger.exception.call_args.args[0]


def test_the_queued_task_runs_the_qa_backfill(backfills):
    backfills.qa_library.return_value = 7
    task = celery_app_module.celery_app.tasks["chroma.backfill_qa_library"]

    # The real task object, not the stub the fixture put on the module.
    assert task.run() == 7
    backfills.qa_library.assert_called_once_with()


def test_a_forked_child_never_uses_its_parents_client_or_model(held):
    """A prefork child is a copy of the main process. Whatever Chroma state it
    inherited, it builds its own: an inherited client's runtime threads do not
    exist after fork and its SQLite handle is shared with the parent."""
    parent_pid = os.getpid() + 1
    chroma_service._owner_pid = parent_pid

    worker_process_init.send(sender=None)

    assert chroma_service._client is None
    assert chroma_service._embedding_function is None
    assert SentenceTransformerEmbeddingFunction.models == {}
    assert SharedSystemClient._identifier_to_system == {}
    # Never closed: closing would stop a System whose threads are the
    # parent's. Kept referenced, so collection never runs its teardown either.
    held.client.close.assert_not_called()
    kept = chroma_service._inherited[0]
    assert held.client in kept and held.embedding_function in kept
    assert {"persist-dir": held.system} in kept and {"the-model": held.model} in kept


def test_the_process_that_opened_the_client_keeps_it(held):
    """The solo pool sends ``worker_process_init`` in the worker's own
    process, which is not a fork: nothing there is inherited."""
    worker_process_init.send(sender=None)

    assert chroma_service._client is held.client
    assert chroma_service._embedding_function is held.embedding_function
    assert SentenceTransformerEmbeddingFunction.models == {"the-model": held.model}
    assert chroma_service._inherited == []
