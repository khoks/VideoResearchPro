"""usage_service: the metering scope, the meter on the LLM factory, the
YouTube hook and the write (E-5.2). The production callers have their own
tests (tests/test_routers/test_usage_metering.py and
tests/test_tasks/test_usage_metering_tasks.py); this file pins the mechanism
they share.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pytest
from langchain_core.outputs import ChatGeneration, LLMResult

from app.models.api_quota_log import ApiQuotaLog
from app.models.quota_usage import QuotaUsage
from app.models.usage_record import UsageRecord
from app.services import llm_service, quota_metering_service, quota_service, usage_service
from app.services.llm_routing import USE_CASE_REGISTRY
from tests.usage_helpers import call_llm, metered_llms, usage_rows, youtube_network  # noqa: F401


def test_every_registered_use_case_is_charged_to_a_named_feature():
    """A new use case must say which feature it bills to, or its calls land
    under "other" on everyone's usage page."""
    missing = sorted(set(USE_CASE_REGISTRY) - set(usage_service.USE_CASE_FEATURES))
    assert missing == []
    assert set(usage_service.USE_CASE_FEATURES.values()) <= set(usage_service.FEATURES)
    assert set(usage_service.YOUTUBE_FEATURES) == set(quota_service.OPERATION_COSTS)


def test_calls_inside_a_scope_are_written_to_the_tenant_when_it_closes(db, test_user, metered_llms):
    with usage_service.metered(db, test_user.id):
        call_llm("library_qa_formulate_answer")
        call_llm("library_qa_refine_context")
        assert usage_rows(db, test_user.id) == {}, "nothing is written while the scope is open"

    assert usage_rows(db, test_user.id) == {
        ("library_qa", "llm_calls"): 2,
        ("library_qa", "llm_tokens_in"): 200,
        ("library_qa", "llm_tokens_out"): 40,
    }
    # The daily totals /auth/quota reports are fed by the same write.
    assert quota_metering_service.get_usage(db, test_user.id, "llm_tokens_in") == 200
    assert quota_metering_service.get_usage(db, test_user.id, "llm_tokens_out") == 40


def test_no_scope_means_nothing_is_recorded(db, test_user, metered_llms):
    call_llm("qa_formulate_answer")
    assert db.query(UsageRecord).count() == 0


def test_mutation_without_the_meter_on_the_factory_nothing_is_recorded(db, test_user, metered_llms, monkeypatch):
    """Mutation check: take the ``attach`` call out of ``get_llm_for`` and
    the scope sees no calls, which the test above would catch."""
    monkeypatch.setattr(llm_service.usage_service, "attach", lambda llm, use_case, tenant_id=None: llm)
    with usage_service.metered(db, test_user.id):
        call_llm("qa_formulate_answer")
    assert usage_rows(db, test_user.id) == {}


def test_byok_context_is_a_scope_for_its_tenant(db, test_user, metered_llms):
    with llm_service.byok_context(test_user.id, db):
        call_llm("knowledge_extract_batch")
    assert usage_rows(db, test_user.id)[("knowledge", "llm_tokens_in")] == 100


def test_nested_scopes_for_one_tenant_write_once_and_the_outer_feature_wins(db, test_user, metered_llms):
    with usage_service.metered(db, test_user.id, feature="saved_search"):
        with usage_service.metered(db, test_user.id, feature="library_qa"):
            call_llm("qa_sub_query_expansion")
        with llm_service.byok_context(test_user.id, db):
            call_llm("saved_search_judge")
        assert usage_rows(db, test_user.id) == {}, "inner scopes join the outer one"
    assert usage_rows(db, test_user.id) == {
        ("saved_search", "llm_calls"): 2,
        ("saved_search", "llm_tokens_in"): 200,
        ("saved_search", "llm_tokens_out"): 40,
    }


def test_an_inner_feature_applies_when_the_outer_scope_named_none(db, test_user, metered_llms):
    with usage_service.metered(db, test_user.id):
        with usage_service.metered(db, test_user.id, feature="library_qa"):
            call_llm("qa_sub_query_expansion")
        call_llm("qa_sub_query_expansion")
    rows = usage_rows(db, test_user.id)
    assert rows[("library_qa", "llm_calls")] == 1
    assert rows[("job_qa", "llm_calls")] == 1


def test_a_scope_for_another_tenant_is_its_own(db, test_user, metered_llms):
    from app.services import auth_service

    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    with usage_service.metered(db, test_user.id):
        with usage_service.metered(db, other.id):
            call_llm("report_compose")
        call_llm("report_map_chunks")
    assert usage_rows(db, other.id) == {
        ("report", "llm_calls"): 1, ("report", "llm_tokens_in"): 100, ("report", "llm_tokens_out"): 20,
    }
    assert usage_rows(db, test_user.id)[("report", "llm_calls")] == 1


def test_amounts_accumulate_across_scopes_into_one_row(db, test_user, metered_llms):
    for _ in range(3):
        with usage_service.metered(db, test_user.id):
            call_llm("qa_history_formulate_answer")
    rows = db.query(UsageRecord).filter_by(tenant_id=test_user.id, metric="llm_tokens_in").all()
    assert [r.amount for r in rows] == [300]
    assert quota_metering_service.get_usage(db, test_user.id, "llm_tokens_in") == 300


def test_local_models_without_usage_still_count_calls(db, test_user, metered_llms):
    metered_llms.report_usage = False
    with usage_service.metered(db, test_user.id):
        call_llm("temporal_scope_extract")
    assert usage_rows(db, test_user.id) == {("ingest", "llm_calls"): 1}


def test_calls_from_a_thread_pool_count_when_the_client_is_built_in_scope(db, test_user, metered_llms):
    """The meter rides on the client, so a pool thread with an empty context
    (report map batches) still counts against the scope it was built in."""
    from langchain_core.messages import HumanMessage

    with usage_service.metered(db, test_user.id):
        llm = llm_service.get_llm_for("report_map_chunks")
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: llm.invoke([HumanMessage(content=str(i))]), range(8)))
    assert usage_rows(db, test_user.id)[("report", "llm_calls")] == 8


def test_report_map_batches_see_the_callers_context(db, test_user):
    """report_agent._map_in_context: each batch runs in a copy of the task's
    context, so BYOK, the user's model overrides and the meter reach it."""
    from app.agents.report_agent import _map_in_context

    with usage_service.metered(db, test_user.id):
        with ThreadPoolExecutor(max_workers=3) as pool:
            seen = _map_in_context(pool, lambda i: (i, getattr(usage_service.current_scope(), "tenant_id", None)), range(5))
        with ThreadPoolExecutor(max_workers=3) as pool:
            bare = list(pool.map(lambda i: getattr(usage_service.current_scope(), "tenant_id", None), range(3)))
    assert seen == [(i, test_user.id) for i in range(5)]
    assert bare == [None, None, None], "a plain pool.map loses the context (the bug _map_in_context fixes)"


def test_tokens_fall_back_to_the_provider_raw_usage():
    from langchain_core.messages import AIMessage

    gen = ChatGeneration(message=AIMessage(content="x"))
    assert usage_service.tokens_from_result(
        LLMResult(generations=[[gen]], llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    ) == (7, 3)
    assert usage_service.tokens_from_result(
        LLMResult(generations=[[gen]], llm_output={"usage": {"input_tokens": 5, "output_tokens": 2}})
    ) == (5, 2)
    assert usage_service.tokens_from_result(LLMResult(generations=[[gen]])) == (None, None)


def _three(feature, calls=1):
    return {(feature, "llm_calls"): calls, (feature, "llm_tokens_in"): 100 * calls,
            (feature, "llm_tokens_out"): 20 * calls}


def _job(tenant_id, topic="meter-probe"):
    from app.models.job import Job

    return Job(job_type="topic", topic=topic, num_videos=1, tenant_id=tenant_id)


def _jobs(db, topic="meter-probe"):
    from app.models.job import Job

    db.expire_all()
    return db.query(Job).filter(Job.topic == topic).count()


def test_a_session_with_pending_changes_is_not_committed_by_the_meter(db, test_user, metered_llms):
    """The meter writes through a session of its own, so the caller's
    unflushed change is neither committed nor discarded, and the tokens it
    spent are recorded whatever the caller then does."""
    test_user.failed_login_attempts = 4
    with usage_service.metered(db, test_user.id):
        call_llm("echo_draft")
    assert db.is_modified(test_user), "the caller's change is still pending, not committed"
    db.rollback()
    db.expire_all()
    assert test_user.failed_login_attempts != 4
    assert usage_rows(db, test_user.id) == _three("echo_draft"), "spent, so recorded"


def test_flushed_work_is_not_committed_by_the_meter(db, test_user, metered_llms):
    """Review finding: a flushed write leaves the identity map clean. The
    meter must still see it, wait for the caller's transaction, and never
    commit it; a rollback must take the work away and leave the usage."""
    with usage_service.metered(db, test_user.id):
        db.add(_job(test_user.id))
        db.flush()
        call_llm("echo_extract_signals")
    assert usage_rows(db, test_user.id) == {}, "waits while the caller's write transaction is open"
    db.rollback()
    assert _jobs(db) == 0, "the meter committed the caller's flushed work"
    assert usage_rows(db, test_user.id) == _three("echo_signals"), "written once the transaction ended"


def test_flushed_work_and_usage_both_land_when_the_caller_commits(db, test_user, metered_llms):
    with usage_service.metered(db, test_user.id):
        db.add(_job(test_user.id))
        db.flush()
        call_llm("report_compose")
    db.commit()
    assert _jobs(db) == 1
    assert usage_rows(db, test_user.id) == _three("report")


def test_usage_waiting_on_a_flushed_transaction_is_written_when_the_session_closes(db, test_user, metered_llms):
    """A Celery task that raised closes its session without committing
    (``echo_tasks.extract_signals_task``): the work goes, the usage stays."""
    from tests.conftest import TestingSessionLocal

    task_db = TestingSessionLocal()
    with usage_service.metered(task_db, test_user.id):
        task_db.add(_job(test_user.id))
        task_db.flush()
        call_llm("knowledge_extract_batch")
    task_db.close()

    assert _jobs(db) == 0
    assert usage_rows(db, test_user.id) == _three("knowledge")


def test_a_core_dml_statement_is_seen_as_written(db, test_user, metered_llms):
    from sqlalchemy import update

    from app.models.user import User

    with usage_service.metered(db, test_user.id):
        db.execute(update(User).where(User.id == test_user.id).values(failed_login_attempts=7))
        call_llm("echo_draft")
    db.rollback()
    db.expire_all()
    assert test_user.failed_login_attempts != 7, "the meter committed the caller's UPDATE"
    assert usage_rows(db, test_user.id) == _three("echo_draft")


def test_a_write_on_the_raw_connection_is_seen_on_sqlite(db, test_user, metered_llms):
    """No session event sees a statement run on ``db.connection()``; the
    SQLite connection's own transaction state does."""
    with usage_service.metered(db, test_user.id):
        db.connection().exec_driver_sql(
            "UPDATE users SET failed_login_attempts = 9 WHERE id = ?", (test_user.id,)
        )
        call_llm("echo_draft")
    db.rollback()
    db.expire_all()
    assert test_user.failed_login_attempts != 9, "the meter committed the caller's raw UPDATE"
    assert usage_rows(db, test_user.id) == _three("echo_draft")


def test_a_failing_meter_write_never_rolls_back_the_callers_work(db, test_user, metered_llms, monkeypatch):
    """Before: a failed upsert rolled back the caller's session, dropping its
    flushed rows and its unflushed ones while the caller carried on."""
    def broken(*a, **k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(usage_service, "_write", broken)
    with usage_service.metered(db, test_user.id):
        db.add(_job(test_user.id, topic="flushed"))
        db.flush()
        call_llm("echo_draft")
    db.commit()
    with usage_service.metered(db, test_user.id):
        db.add(_job(test_user.id, topic="unflushed"))
        call_llm("echo_draft")
    db.commit()
    assert _jobs(db, "flushed") == 1
    assert _jobs(db, "unflushed") == 1
    assert usage_rows(db, test_user.id) == {}


def test_the_meters_own_write_does_not_leave_the_caller_marked_as_written(db, test_user, metered_llms):
    """Two scopes in a row on a clean session both write at once: the
    bookkeeping clears when a transaction ends."""
    db.add(_job(test_user.id))
    db.commit()
    for _ in range(2):
        with usage_service.metered(db, test_user.id):
            call_llm("echo_draft")
        assert usage_rows(db, test_user.id)[("echo_draft", "llm_calls")] >= 1
    assert usage_rows(db, test_user.id) == _three("echo_draft", calls=2)


def test_pending_changes_and_usage_commit_together(db, test_user, metered_llms):
    test_user.failed_login_attempts = 3
    with usage_service.metered(db, test_user.id):
        call_llm("echo_draft")
    db.commit()
    assert usage_rows(db, test_user.id)[("echo_draft", "llm_calls")] == 1
    db.expire_all()
    assert test_user.failed_login_attempts == 3


def test_a_failing_block_still_records_what_it_spent(db, test_user, metered_llms):
    with pytest.raises(RuntimeError):
        with usage_service.metered(db, test_user.id):
            call_llm("knowledge_synthesize_report")
            raise RuntimeError("parse failed after the call")
    assert usage_rows(db, test_user.id)[("knowledge", "llm_tokens_out")] == 20


def test_youtube_requests_are_charged_to_the_scope_and_still_logged_install_wide(db, test_user, youtube_network):
    from app.services import youtube_service

    youtube_network.responses = {
        "videos": {"items": [{"id": "v1", "snippet": {"title": "t"}, "contentDetails": {"duration": "PT1M"}}]},
        "search": {"items": []},
    }
    with usage_service.metered(db, test_user.id):
        youtube_service.get_video_details(["v1"])
        youtube_service.search_videos("tariffs", max_results=5)
    youtube_service.get_video_details(["v1"])  # no scope: install-wide only

    assert usage_rows(db, test_user.id) == {("video_metadata", "youtube_units"): 1, ("youtube_search", "youtube_units"): 100}
    assert quota_metering_service.get_usage(db, test_user.id, "youtube_units") == 101
    db.expire_all()
    assert sorted((r.operation, r.units) for r in db.query(ApiQuotaLog)) == [
        ("search", 100), ("videos", 1), ("videos", 1),
    ]
    assert sum(youtube_network.redis.counts.values()) == 102


def test_summary_reads_only_the_callers_rows_in_the_window(db, test_user):
    today = date(2026, 11, 3)
    rows = [
        (test_user.id, today, "library_qa", "llm_tokens_in", 500),
        (test_user.id, today, "library_qa", "llm_calls", 2),
        (test_user.id, today - timedelta(days=29), "report", "llm_tokens_in", 9000),
        (test_user.id, today - timedelta(days=30), "report", "llm_tokens_in", 1),  # outside the window
        (test_user.id, today - timedelta(days=3), "youtube_search", "youtube_units", 200),
        ("someone-else", today, "library_qa", "llm_tokens_in", 77),
    ]
    for tenant, day, feature, metric, amount in rows:
        db.add(UsageRecord(tenant_id=tenant, day=day, feature=feature, metric=metric, amount=amount))
    db.commit()

    out = usage_service.summary(db, test_user.id, today=today)
    assert out["window_start"] == today - timedelta(days=29)
    assert out["metered_since"] == today - timedelta(days=30)
    by = {f["feature"]: f for f in out["features"]}
    assert [f["feature"] for f in out["features"]] == ["report", "library_qa", "youtube_search"]
    assert by["report"]["last_30_days"]["llm_tokens_in"] == 9000 and by["report"]["today"]["llm_tokens_in"] == 0
    assert by["library_qa"]["today"] == {"llm_tokens_in": 500, "llm_tokens_out": 0, "llm_calls": 2, "youtube_units": 0}
    assert by["youtube_search"]["label"] == "Searches (YouTube)"
    assert by["youtube_search"]["last_30_days"]["youtube_units"] == 200
    assert out["totals"]["today"]["llm_tokens_in"] == 500
    assert out["totals"]["last_30_days"]["llm_tokens_in"] == 9500


def test_record_writes_one_amount_now(db, test_user):
    usage_service.record(db, test_user.id, "author", "llm_tokens_out", 42)
    assert usage_rows(db, test_user.id) == {("author", "llm_tokens_out"): 42}
    with pytest.raises(ValueError):
        usage_service.record(db, test_user.id, "author", "dollars", 1)


def test_quota_row_matches_record_usage_bucket(db, test_user, metered_llms):
    """The meter's daily total lands in the same quota_usage row that
    quota_metering_service.record_usage writes, not a parallel one."""
    quota_metering_service.record_usage(db, test_user.id, "llm_tokens_in", 5)
    with usage_service.metered(db, test_user.id):
        call_llm("qa_formulate_answer")
    rows = db.query(QuotaUsage).filter_by(user_id=test_user.id, resource="llm_tokens_in").all()
    assert len(rows) == 1 and rows[0].consumed == 105
    start = rows[0].period_start
    assert (start.year, start.month, start.day) == tuple(datetime.now(timezone.utc).timetuple()[:3])


def test_concurrent_report_map_batches_build_their_clients_inside_the_tasks_scope(db, test_user, monkeypatch):
    """At the production caller of the pool: ``report_agent.map_chunks`` with
    four workers builds each map client on a pool thread. Every one of them
    must see the task's scope (and so its BYOK key and model overrides);
    with a plain ``pool.map`` none does."""
    from unittest.mock import patch

    from app.agents import report_agent
    from app.config import settings
    from tests.test_agents.test_map_batching import _chunk, _EchoLLM

    monkeypatch.setattr(settings, "REPORT_MAP_BATCH_TOKENS", 700)
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "source")
    monkeypatch.setattr(settings, "REPORT_MAP_CONCURRENCY", 4)
    seen: list = []
    llm = _EchoLLM(delays={"a": 0.05})

    def factory(use_case, **kwargs):
        seen.append((use_case, getattr(usage_service.current_scope(), "tenant_id", None),
                     llm_service._byok_context.get()[0]))
        return llm

    chunks = [_chunk(v, i) for v in ("a", "b", "c", "d") for i in range(2)]
    with usage_service.metered(db, test_user.id), llm_service.byok_context(test_user.id, db):
        with patch.object(report_agent, "get_llm_for", side_effect=factory):
            report_agent.map_chunks({"job_type": "topic", "topic": "t", "transcript_chunks": chunks})
    assert seen and all(s == ("report_map_chunks", test_user.id, test_user.id) for s in seen), seen
