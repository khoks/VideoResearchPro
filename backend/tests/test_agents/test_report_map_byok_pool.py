"""T-5.6.12: report map batches on a pool run on the tenant's own key.

A pool thread runs in a copy of the task's context (``_map_in_context``), and
that copy held the task's ``Session``. ``get_llm_for`` looked the BYOK key up
through it, on the pool thread. A ``Session`` belongs to one thread, and
``_resolve_byok_api_key`` answers any exception with the install's key, so the
tenant's work could run on the install's bill with nothing to show for it.

These tests use a real thread pool and a real SQLite connection with
``check_same_thread=True``, which refuses exactly this: a read on the task's
session from another thread raises. The production engine turns that check
off, and ``_llm_for`` holds a lock around the lookup, so there the same read
usually goes through, by luck and not by design. This engine makes the fault
visible: ``test_mutation_...`` shows the lookup falling back without the fix,
which is what these tests fail on against the old code.
"""
from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents import report_agent
from app.agents.report_agent import _map_in_context
from app.config import settings
from app.database import Base
from app.models.user import User
from app.models.user_llm_override import UserLLMOverride
from app.services import auth_service, byok_service, llm_service
from tests.test_agents.test_map_batching import _chunk, _EchoLLM

USER_KEY = "fake-placeholder-not-a-key-openai"
CLAUDE_KEY = "fake-placeholder-not-a-key-claude"


@pytest.fixture(autouse=True)
def _stable_fernet(monkeypatch):
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


@pytest.fixture
def task_session(tmp_path):
    """The task's session, on one connection that refuses other threads, with
    a transaction open, as a task's is once it has read its job."""
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'task.db').as_posix()}",
        connect_args={"check_same_thread": True},  # a file database defaults to False
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _owner(db, tier: str = "studio", **keys) -> User:
    user = auth_service.create_user(db, email=f"{tier}-{len(keys)}@example.com", password="pw" * 6)
    user.tier = tier
    db.commit()
    for provider, secret in keys.items():
        byok_service.set_credential(db, user_id=user.id, provider=provider, secret=secret)
    db.query(User).filter(User.id == user.id).first()  # the task's open read
    return user


@pytest.fixture
def built(monkeypatch):
    """Every client ``get_llm_for`` builds: (provider, the key it was given)."""
    clients: list[tuple[str, str | None]] = []
    llm = _EchoLLM(delays={"a": 0.02, "b": 0.01})

    def build(cfg, temperature, max_tokens, *, byok_api_key=None):
        clients.append((cfg.provider, byok_api_key))
        return llm

    monkeypatch.setattr(llm_service, "_build_from_config", build)
    return clients


def _map_on_a_pool(monkeypatch, tenant_id, db) -> dict:
    """``map_chunks``, the production caller of the pool, with four workers.
    Two sizes of batch make two clients, so the lookup runs more than once."""
    monkeypatch.setattr(settings, "REPORT_MAP_BATCH_TOKENS", 700)
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "source")
    monkeypatch.setattr(settings, "REPORT_MAP_CONCURRENCY", 4)
    chunks = [_chunk(v, i, words=40 if v in ("a", "b") else 120) for v in ("a", "b", "c", "d") for i in range(2)]
    with llm_service.byok_context(tenant_id, db):
        return report_agent.map_chunks({"job_type": "topic", "topic": "t", "transcript_chunks": chunks})


def test_map_batches_on_a_pool_run_on_the_tenants_own_key(task_session, built, monkeypatch):
    owner = _owner(task_session, openai=USER_KEY)

    out = _map_on_a_pool(monkeypatch, owner.id, task_session)

    assert out["processing_notes"]["map_batches_failed"] == 0
    assert built, "no client was built on the pool"
    assert set(built) == {("openai", USER_KEY)}


def test_mutation_without_the_keys_handed_over_the_lookup_falls_back_to_the_install(
    task_session, built, monkeypatch
):
    """The old code: the pool thread reads through the task's session, the
    connection refuses, and the fallback swallows it. Same run, same user."""
    owner = _owner(task_session, openai=USER_KEY)
    monkeypatch.setattr(report_agent, "byok_keys_for_pool", contextlib.nullcontext)

    _map_on_a_pool(monkeypatch, owner.id, task_session)

    assert built and set(built) == {("openai", None)}


def test_a_pool_thread_gets_the_key_of_whichever_provider_the_tenant_pinned(task_session, built, monkeypatch):
    """The key is read before the pool starts, for every provider: one left
    out would read as "no key" on the thread, and fall back all the same."""
    owner = _owner(task_session, openai=USER_KEY, anthropic=CLAUDE_KEY)
    task_session.add(UserLLMOverride(
        user_id=owner.id, use_case="report_map_chunks",
        provider="anthropic", model="claude-sonnet-5", reasoning="off",
    ))
    task_session.commit()

    _map_on_a_pool(monkeypatch, owner.id, task_session)

    assert built and set(built) == {("anthropic", CLAUDE_KEY)}


def test_a_tier_without_keys_stays_on_the_install_key_on_a_pool(task_session, built, monkeypatch):
    """The tier gate still decides: a stored key from before a downgrade."""
    owner = _owner(task_session, tier="free", openai=USER_KEY)

    _map_on_a_pool(monkeypatch, owner.id, task_session)

    assert built and set(built) == {("openai", None)}


def test_a_tenant_with_no_key_stays_on_the_install_key_on_a_pool(task_session, built, monkeypatch):
    owner = _owner(task_session)

    _map_on_a_pool(monkeypatch, owner.id, task_session)

    assert built and set(built) == {("openai", None)}


def test_a_pool_thread_holds_the_tenant_and_never_the_session(task_session):
    owner = _owner(task_session)

    with llm_service.byok_context(owner.id, task_session):
        with ThreadPoolExecutor(max_workers=2) as pool:
            seen = _map_in_context(pool, lambda _: llm_service._byok_context.get(), range(3))
        assert llm_service._byok_context.get() == (owner.id, task_session), "the task's context comes back"

    assert seen == [(owner.id, None)] * 3
    assert llm_service._byok_keys.get() is None, "no key outlives the pool"


def test_a_pool_that_raises_still_takes_the_keys_back_out_of_the_context(task_session):
    owner = _owner(task_session, openai=USER_KEY)

    def boom(_):
        raise RuntimeError("a batch broke")

    with llm_service.byok_context(owner.id, task_session):
        with ThreadPoolExecutor(max_workers=2) as pool:
            with pytest.raises(RuntimeError):
                _map_in_context(pool, boom, range(2))
        assert llm_service._byok_context.get() == (owner.id, task_session)
        assert llm_service._byok_keys.get() is None


def test_map_in_context_outside_any_tenant_reads_nothing_and_uses_no_key():
    """A script's report, or a test: nothing to resolve and nothing to raise."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        seen = _map_in_context(pool, lambda _: llm_service._byok_key("openai", None, None), range(2))
    assert seen == [None, None]


def test_a_nested_pool_keeps_the_keys_it_was_handed(task_session):
    """Inside the block there is no session to read through, so a second pool
    must keep the keys, not read them as missing."""
    owner = _owner(task_session, openai=USER_KEY)

    with llm_service.byok_context(owner.id, task_session), llm_service.byok_keys_for_pool():
        with llm_service.byok_keys_for_pool():
            assert llm_service._byok_key("openai", owner.id, None) == USER_KEY
