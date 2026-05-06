"""Tests for I-3 Echo foundation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.personal_context import PersonalContext
from app.services import auth_service, echo_service
from app.services.echo_service import (
    SUPPORTED_KINDS,
    UnsupportedKindError,
    delete_context,
    get_context,
    is_ready,
    list_context,
    list_connectors,
    record_context,
    register_connector,
    revoke_source,
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unsupported_kind_rejected(db):
    user = auth_service.create_user(db, email="ek1@x.com", password="pw" * 6)
    with pytest.raises(UnsupportedKindError):
        record_context(
            db,
            user_id=user.id,
            kind="not-a-real-kind",
            key="x",
            value="y",
            source="manual",
        )


def test_supported_kinds_includes_all_known():
    expected = {
        "location", "interest", "hobby", "work", "talent",
        "skill", "personality_trait", "life_event",
        "daily_routine", "place",
    }
    assert expected.issubset(SUPPORTED_KINDS)


def test_empty_source_rejected(db):
    user = auth_service.create_user(db, email="ek2@x.com", password="pw" * 6)
    with pytest.raises(ValueError):
        record_context(
            db,
            user_id=user.id,
            kind="interest",
            key="cooking",
            value="yes",
            source="",
        )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_record_context_creates_row(db):
    user = auth_service.create_user(db, email="r1@x.com", password="pw" * 6)
    row = record_context(
        db,
        user_id=user.id,
        kind="interest",
        key="cooking",
        value="loves Italian cuisine",
        source="manual",
    )
    assert row.id is not None
    assert row.value == "loves Italian cuisine"
    assert row.source == "manual"
    assert row.confidence == 1.0


def test_record_context_upserts_on_same_user_kind_key(db):
    user = auth_service.create_user(db, email="r2@x.com", password="pw" * 6)
    a = record_context(
        db, user_id=user.id, kind="work", key="employer",
        value="ACME", source="manual",
    )
    b = record_context(
        db, user_id=user.id, kind="work", key="employer",
        value="UMBRELLA", source="manual",
    )
    assert a.id == b.id  # same row, updated in place
    assert b.value == "UMBRELLA"
    # Only one row in the DB.
    rows = db.query(PersonalContext).filter(
        PersonalContext.user_id == user.id
    ).all()
    assert len(rows) == 1


def test_record_context_clamps_confidence(db):
    user = auth_service.create_user(db, email="r3@x.com", password="pw" * 6)
    a = record_context(
        db, user_id=user.id, kind="skill", key="python",
        value="senior", source="manual", confidence=2.5,
    )
    b = record_context(
        db, user_id=user.id, kind="skill", key="rust",
        value="beginner", source="manual", confidence=-0.5,
    )
    assert a.confidence == 1.0
    assert b.confidence == 0.0


def test_record_context_json_encodes_non_string_value(db):
    user = auth_service.create_user(db, email="r4@x.com", password="pw" * 6)
    row = record_context(
        db, user_id=user.id, kind="personality_trait",
        key="big5", value={"openness": 0.8, "conscientiousness": 0.6},
        source="manual",
    )
    import json
    parsed = json.loads(row.value)
    assert parsed["openness"] == 0.8


def test_get_context_returns_none_when_missing(db):
    user = auth_service.create_user(db, email="g1@x.com", password="pw" * 6)
    assert get_context(db, user.id, "interest", "cooking") is None


def test_list_context_filters_by_kind(db):
    user = auth_service.create_user(db, email="l1@x.com", password="pw" * 6)
    record_context(db, user_id=user.id, kind="interest", key="a",
                   value="v", source="manual")
    record_context(db, user_id=user.id, kind="hobby", key="b",
                   value="v", source="manual")
    interests = list_context(db, user.id, kind="interest")
    hobbies = list_context(db, user.id, kind="hobby")
    assert len(interests) == 1 and interests[0].key == "a"
    assert len(hobbies) == 1 and hobbies[0].key == "b"


def test_list_context_excludes_expired_by_default(db):
    user = auth_service.create_user(db, email="l2@x.com", password="pw" * 6)
    expired = record_context(
        db, user_id=user.id, kind="work", key="employer-old",
        value="OLD", source="manual",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    record_context(
        db, user_id=user.id, kind="work", key="employer-current",
        value="CURRENT", source="manual",
    )
    rows = list_context(db, user.id)
    keys = {r.key for r in rows}
    assert "employer-current" in keys
    assert "employer-old" not in keys


def test_list_context_include_expired_returns_all(db):
    user = auth_service.create_user(db, email="l3@x.com", password="pw" * 6)
    record_context(
        db, user_id=user.id, kind="work", key="old",
        value="X", source="manual",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    rows = list_context(db, user.id, include_expired=True)
    assert len(rows) == 1


def test_list_context_per_user_isolation(db):
    a = auth_service.create_user(db, email="la@x.com", password="pw" * 6)
    b = auth_service.create_user(db, email="lb@x.com", password="pw" * 6)
    record_context(db, user_id=a.id, kind="interest", key="x",
                   value="A", source="manual")
    record_context(db, user_id=b.id, kind="interest", key="x",
                   value="B", source="manual")
    a_rows = list_context(db, a.id)
    b_rows = list_context(db, b.id)
    assert len(a_rows) == 1 and a_rows[0].value == "A"
    assert len(b_rows) == 1 and b_rows[0].value == "B"


def test_delete_context_returns_true_when_existing(db):
    user = auth_service.create_user(db, email="d1@x.com", password="pw" * 6)
    record_context(db, user_id=user.id, kind="interest", key="x",
                   value="v", source="manual")
    assert delete_context(db, user.id, "interest", "x") is True
    assert get_context(db, user.id, "interest", "x") is None


def test_delete_context_returns_false_when_missing(db):
    user = auth_service.create_user(db, email="d2@x.com", password="pw" * 6)
    assert delete_context(db, user.id, "interest", "missing") is False


def test_revoke_source_deletes_only_matching_rows(db):
    user = auth_service.create_user(db, email="rs@x.com", password="pw" * 6)
    record_context(db, user_id=user.id, kind="interest", key="a",
                   value="v", source="manual")
    record_context(db, user_id=user.id, kind="interest", key="b",
                   value="v", source="spotify_history")
    record_context(db, user_id=user.id, kind="interest", key="c",
                   value="v", source="spotify_history")

    n = revoke_source(db, user.id, "spotify_history")
    assert n == 2
    remaining = list_context(db, user.id)
    assert len(remaining) == 1 and remaining[0].source == "manual"


# ---------------------------------------------------------------------------
# Cold-start gate
# ---------------------------------------------------------------------------


def test_is_ready_false_on_empty_user(db):
    user = auth_service.create_user(db, email="cs1@x.com", password="pw" * 6)
    r = is_ready(db, user.id)
    assert r.ready is False
    assert r.total_rows == 0
    assert r.distinct_sources == 0
    assert r.has_personality_trait is False


def test_is_ready_true_when_thresholds_met(db):
    user = auth_service.create_user(db, email="cs2@x.com", password="pw" * 6)
    # Use small thresholds so the test stays fast.
    for i in range(5):
        record_context(
            db, user_id=user.id, kind="interest", key=f"k{i}",
            value="v", source="manual",
        )
    record_context(
        db, user_id=user.id, kind="hobby", key="h",
        value="v", source="spotify_history",
    )
    record_context(
        db, user_id=user.id, kind="personality_trait", key="introvert",
        value="0.7", source="youtube_watch_history",
    )

    r = is_ready(db, user.id, total_threshold=3, sources_threshold=3)
    assert r.ready is True
    assert r.total_rows == 7
    assert r.distinct_sources == 3
    assert r.has_personality_trait is True


def test_is_ready_false_when_no_personality_trait(db):
    user = auth_service.create_user(db, email="cs3@x.com", password="pw" * 6)
    for i in range(3):
        record_context(
            db, user_id=user.id, kind="interest", key=f"k{i}",
            value="v", source=f"s{i}",
        )
    r = is_ready(db, user.id, total_threshold=3, sources_threshold=3)
    assert r.ready is False
    assert r.has_personality_trait is False


# ---------------------------------------------------------------------------
# Connector registry (v1 ships empty; future PRs populate)
# ---------------------------------------------------------------------------


def test_list_connectors_starts_empty():
    assert list_connectors() == []


def test_register_connector_adds_to_registry():
    class FakeConnector:
        name = "fake_test_connector"

        def authorize_url(self, user, redirect_uri):
            return ""

        def revoke(self, db, user):
            pass

        def sync(self, db, user):
            return 0

        def supported_kinds(self):
            return {"interest"}

    register_connector(FakeConnector())
    assert "fake_test_connector" in list_connectors()


# ---------------------------------------------------------------------------
# Endpoint integration
# ---------------------------------------------------------------------------


def test_echo_endpoints_require_studio(unauthenticated_client, db):
    """Free / Pro tier users get 403 on every /echo route."""
    user = auth_service.create_user(db, email="ec-free@x.com", password="pw" * 6)
    token, _ = auth_service.create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    r1 = unauthenticated_client.get("/api/v1/echo/status", headers=headers)
    r2 = unauthenticated_client.get("/api/v1/echo/context", headers=headers)
    r3 = unauthenticated_client.post(
        "/api/v1/echo/context",
        json={"kind": "interest", "key": "x", "value": "y"},
        headers=headers,
    )
    r4 = unauthenticated_client.get("/api/v1/echo/connectors", headers=headers)
    assert r1.status_code == 403
    assert r2.status_code == 403
    assert r3.status_code == 403
    assert r4.status_code == 403


def test_echo_endpoints_require_auth(unauthenticated_client):
    r = unauthenticated_client.get("/api/v1/echo/status")
    assert r.status_code == 401


def _studio_headers(db, email: str):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


def test_echo_status_returns_diagnostics(unauthenticated_client, db):
    user, headers = _studio_headers(db, "ec-st@x.com")
    r = unauthenticated_client.get("/api/v1/echo/status", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert body["total_rows"] == 0
    assert body["threshold_total"] == 100  # default


def test_echo_context_post_creates_row(unauthenticated_client, db):
    user, headers = _studio_headers(db, "ec-pc@x.com")
    r = unauthenticated_client.post(
        "/api/v1/echo/context",
        json={"kind": "interest", "key": "cooking", "value": "Italian"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "interest"
    assert body["source"] == "manual"


def test_echo_context_post_400_on_unknown_kind(unauthenticated_client, db):
    _, headers = _studio_headers(db, "ec-bad@x.com")
    r = unauthenticated_client.post(
        "/api/v1/echo/context",
        json={"kind": "not-a-kind", "key": "x", "value": "y"},
        headers=headers,
    )
    assert r.status_code == 400


def test_echo_context_get_returns_user_rows(unauthenticated_client, db):
    user, headers = _studio_headers(db, "ec-list@x.com")
    record_context(db, user_id=user.id, kind="hobby", key="reading",
                   value="fiction", source="manual")
    r = unauthenticated_client.get("/api/v1/echo/context", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["key"] == "reading"


def test_echo_delete_context_404_on_missing(unauthenticated_client, db):
    _, headers = _studio_headers(db, "ec-del@x.com")
    r = unauthenticated_client.delete(
        "/api/v1/echo/context/interest/missing", headers=headers
    )
    assert r.status_code == 404


def test_echo_revoke_source_returns_count(unauthenticated_client, db):
    user, headers = _studio_headers(db, "ec-rev@x.com")
    record_context(db, user_id=user.id, kind="interest", key="a",
                   value="v", source="spotify_history")
    record_context(db, user_id=user.id, kind="interest", key="b",
                   value="v", source="spotify_history")
    record_context(db, user_id=user.id, kind="interest", key="c",
                   value="v", source="manual")

    r = unauthenticated_client.delete(
        "/api/v1/echo/sources/spotify_history", headers=headers
    )
    assert r.status_code == 200
    assert r.json() == {"deleted_count": 2}
