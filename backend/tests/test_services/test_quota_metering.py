"""Tests for T-5.5.5 / T-5.2.5 quota metering."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.quota_usage import QuotaUsage
from app.services import auth_service, quota_metering_service
from app.services.quota_metering_service import (
    QuotaExceededError,
    _period_start,
    check_quota,
    enforce_quota_or_raise,
    get_all_usage,
    get_usage,
    record_usage,
    supported_resources,
)


# ---------------------------------------------------------------------------
# Period boundaries
# ---------------------------------------------------------------------------


def test_period_start_daily_floors_to_midnight():
    now = datetime(2026, 5, 5, 14, 32, 17, tzinfo=timezone.utc)
    p = _period_start(now, "daily")
    assert p.year == 2026 and p.month == 5 and p.day == 5
    assert p.hour == 0 and p.minute == 0 and p.second == 0


def test_period_start_monthly_floors_to_first_of_month():
    now = datetime(2026, 5, 15, 14, 32, 17, tzinfo=timezone.utc)
    p = _period_start(now, "monthly")
    assert p.year == 2026 and p.month == 5 and p.day == 1


def test_period_start_lifetime_is_constant():
    now1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now2 = datetime(2030, 12, 31, tzinfo=timezone.utc)
    assert _period_start(now1, "lifetime") == _period_start(now2, "lifetime")


def test_period_start_unknown_kind_raises():
    with pytest.raises(ValueError):
        _period_start(datetime.now(timezone.utc), "weekly")


# ---------------------------------------------------------------------------
# Resource registry
# ---------------------------------------------------------------------------


def test_supported_resources_includes_known():
    rs = supported_resources()
    for expected in (
        "qa_exchanges",
        "library_qa_exchanges",
        "qa_history_chats",
        "knowledge_extractions",
        "documents",
        "llm_tokens_in",
        "llm_tokens_out",
        "youtube_units",
    ):
        assert expected in rs


# ---------------------------------------------------------------------------
# record_usage / get_usage
# ---------------------------------------------------------------------------


def test_record_usage_creates_row(db):
    user = auth_service.create_user(db, email="m1@x.com", password="pw" * 6)
    record_usage(db, user.id, "qa_exchanges", 1)
    assert get_usage(db, user.id, "qa_exchanges") == 1


def test_record_usage_increments_existing_row(db):
    user = auth_service.create_user(db, email="m2@x.com", password="pw" * 6)
    record_usage(db, user.id, "qa_exchanges", 3)
    record_usage(db, user.id, "qa_exchanges", 5)
    assert get_usage(db, user.id, "qa_exchanges") == 8


def test_record_usage_zero_or_negative_is_noop(db):
    user = auth_service.create_user(db, email="m3@x.com", password="pw" * 6)
    record_usage(db, user.id, "qa_exchanges", 0)
    record_usage(db, user.id, "qa_exchanges", -10)
    assert get_usage(db, user.id, "qa_exchanges") == 0
    assert db.query(QuotaUsage).count() == 0


def test_record_usage_separate_resources_separate_rows(db):
    user = auth_service.create_user(db, email="m4@x.com", password="pw" * 6)
    record_usage(db, user.id, "qa_exchanges", 5)
    record_usage(db, user.id, "knowledge_extractions", 2)
    assert get_usage(db, user.id, "qa_exchanges") == 5
    assert get_usage(db, user.id, "knowledge_extractions") == 2


def test_record_usage_separate_users_separate_rows(db):
    a = auth_service.create_user(db, email="ma@x.com", password="pw" * 6)
    b = auth_service.create_user(db, email="mb@x.com", password="pw" * 6)
    record_usage(db, a.id, "qa_exchanges", 5)
    record_usage(db, b.id, "qa_exchanges", 7)
    assert get_usage(db, a.id, "qa_exchanges") == 5
    assert get_usage(db, b.id, "qa_exchanges") == 7


# ---------------------------------------------------------------------------
# Tier limits → check_quota / enforce_quota
# ---------------------------------------------------------------------------


def test_check_quota_allows_under_limit(db):
    user = auth_service.create_user(db, email="c1@x.com", password="pw" * 6)
    # Free tier: qa_exchanges_per_month = 50
    ok, retry = check_quota(db, user, "qa_exchanges", 1)
    assert ok is True
    assert retry is None


def test_check_quota_blocks_at_limit(db):
    user = auth_service.create_user(db, email="c2@x.com", password="pw" * 6)
    # Free tier qa cap is 50; consume 50.
    record_usage(db, user.id, "qa_exchanges", 50)
    ok, retry = check_quota(db, user, "qa_exchanges", 1)
    assert ok is False
    assert retry is not None  # next month rollover


def test_studio_tier_unlimited_qa_returns_no_retry(db):
    user = auth_service.create_user(db, email="c3@x.com", password="pw" * 6)
    user.tier = "studio"
    db.commit()
    record_usage(db, user.id, "qa_exchanges", 999_999)
    ok, retry = check_quota(db, user, "qa_exchanges", 1)
    assert ok is True
    assert retry is None


def test_enforce_quota_raises_429_when_over(db):
    user = auth_service.create_user(db, email="e1@x.com", password="pw" * 6)
    record_usage(db, user.id, "qa_exchanges", 50)
    with pytest.raises(QuotaExceededError) as exc_info:
        enforce_quota_or_raise(db, user, "qa_exchanges")
    assert exc_info.value.status_code == 429
    detail = exc_info.value.detail
    assert detail["resource"] == "qa_exchanges"
    assert detail["consumed"] == 50
    assert detail["limit"] == 50
    assert detail["retry_after_sec"] is not None


def test_enforce_quota_passes_under_limit(db):
    user = auth_service.create_user(db, email="e2@x.com", password="pw" * 6)
    enforce_quota_or_raise(db, user, "qa_exchanges")  # No raise


# ---------------------------------------------------------------------------
# get_all_usage snapshot
# ---------------------------------------------------------------------------


def test_get_all_usage_returns_every_resource(db):
    user = auth_service.create_user(db, email="snap@x.com", password="pw" * 6)
    record_usage(db, user.id, "qa_exchanges", 3)
    snapshots = get_all_usage(db, user)
    assert len(snapshots) == len(supported_resources())
    by_name = {s.resource: s for s in snapshots}
    assert by_name["qa_exchanges"].consumed == 3
    # qa_history_chats untouched → consumed=0.
    assert by_name["qa_history_chats"].consumed == 0
    # Free tier qa cap from TIER_CAPABILITIES.
    assert by_name["qa_exchanges"].limit == 50


def test_get_all_usage_marks_over_limit(db):
    user = auth_service.create_user(db, email="over@x.com", password="pw" * 6)
    record_usage(db, user.id, "qa_exchanges", 50)
    snapshots = get_all_usage(db, user)
    qa = next(s for s in snapshots if s.resource == "qa_exchanges")
    assert qa.over_limit is True


# ---------------------------------------------------------------------------
# Endpoint integration
# ---------------------------------------------------------------------------


def test_quota_endpoint_returns_full_snapshot(client, db, test_user):
    quota_metering_service.record_usage(db, test_user.id, "qa_exchanges", 7)
    r = client.get("/api/v1/auth/quota")
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "free"
    by_name = {x["resource"]: x for x in body["resources"]}
    assert by_name["qa_exchanges"]["consumed"] == 7
    assert by_name["qa_exchanges"]["limit"] == 50
    assert by_name["qa_exchanges"]["over_limit"] is False


def test_quota_endpoint_requires_auth(unauthenticated_client):
    r = unauthenticated_client.get("/api/v1/auth/quota")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Period rollover
# ---------------------------------------------------------------------------


def test_distinct_periods_keep_separate_rows(db):
    """Two records in different daily periods land in different rows
    (only relevant for daily/monthly; lifetime always uses one row)."""
    user = auth_service.create_user(db, email="rs@x.com", password="pw" * 6)

    # Synthesize a yesterday row directly so we don't depend on time.
    yesterday = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=1)
    db.add(
        QuotaUsage(
            user_id=user.id,
            resource="llm_tokens_in",
            period_kind="daily",
            period_start=yesterday,
            consumed=42,
        )
    )
    db.commit()

    # Today's record creates a new row.
    record_usage(db, user.id, "llm_tokens_in", 10)
    rows = (
        db.query(QuotaUsage)
        .filter(QuotaUsage.user_id == user.id)
        .all()
    )
    assert len(rows) == 2
    # get_usage returns only the current day's value.
    assert get_usage(db, user.id, "llm_tokens_in") == 10
