"""Tests for E-5.2 subscription tier gating.

Covers:
* `Tier` enum ordering / `at_least` semantics.
* `get_user_tier` defaults + bad-value tolerance.
* `has_feature` / `quota_limit` per tier.
* `require_tier` and `require_feature` FastAPI dependencies — 403 path
  and pass-through path.
* User model defaults to `free` tier when not set explicitly.
"""
from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.models.user import User
from app.services import auth_service
from app.services.tier_service import (
    TIER_CAPABILITIES,
    Tier,
    capabilities_for,
    get_user_tier,
    has_feature,
    quota_limit,
    require_feature,
    require_tier,
)


# ---------------------------------------------------------------------------
# Tier enum
# ---------------------------------------------------------------------------


def test_tier_enum_values():
    assert Tier.FREE.value == "free"
    assert Tier.PRO.value == "pro"
    assert Tier.STUDIO.value == "studio"


def test_tier_ordering_via_at_least():
    # Reflexive
    assert Tier.FREE.at_least(Tier.FREE)
    assert Tier.PRO.at_least(Tier.PRO)
    assert Tier.STUDIO.at_least(Tier.STUDIO)
    # Strict ascending
    assert Tier.PRO.at_least(Tier.FREE)
    assert Tier.STUDIO.at_least(Tier.FREE)
    assert Tier.STUDIO.at_least(Tier.PRO)
    # Strict descending
    assert not Tier.FREE.at_least(Tier.PRO)
    assert not Tier.FREE.at_least(Tier.STUDIO)
    assert not Tier.PRO.at_least(Tier.STUDIO)


def test_tier_ranks_strictly_increase():
    assert Tier.FREE.rank < Tier.PRO.rank < Tier.STUDIO.rank


# ---------------------------------------------------------------------------
# User → Tier resolution
# ---------------------------------------------------------------------------


def _make_user(tier: str | None = "free") -> User:
    """Build a User without DB persistence — only `tier` matters here."""
    u = User(email="x@y.z", password_hash="x")
    u.tier = tier  # type: ignore[assignment]
    return u


def test_get_user_tier_free():
    assert get_user_tier(_make_user("free")) is Tier.FREE


def test_get_user_tier_pro_and_studio():
    assert get_user_tier(_make_user("pro")) is Tier.PRO
    assert get_user_tier(_make_user("studio")) is Tier.STUDIO


def test_get_user_tier_defaults_when_unknown_value():
    """Defense-in-depth: an unknown string returns FREE rather than crashing."""
    assert get_user_tier(_make_user("enterprise_xl")) is Tier.FREE
    assert get_user_tier(_make_user("FREE")) is Tier.FREE  # case-insensitive
    assert get_user_tier(_make_user("  pro  ")) is Tier.PRO  # whitespace tolerant


def test_get_user_tier_defaults_when_none():
    """Pre-migration legacy rows have tier=NULL — we still want FREE, not crash."""
    assert get_user_tier(_make_user(None)) is Tier.FREE


# ---------------------------------------------------------------------------
# Capability table
# ---------------------------------------------------------------------------


def test_every_tier_has_capability_row():
    for tier in Tier:
        assert tier in TIER_CAPABILITIES
        cap = TIER_CAPABILITIES[tier]
        assert "youtube_units_per_day" in cap
        assert "llm_tokens_per_day" in cap
        assert "document_count_cap" in cap
        assert "features" in cap


def test_quotas_strictly_increase_or_equal_with_tier():
    # Higher tiers must never have *less* of a resource.
    f, p, s = TIER_CAPABILITIES[Tier.FREE], TIER_CAPABILITIES[Tier.PRO], TIER_CAPABILITIES[Tier.STUDIO]
    assert f["youtube_units_per_day"] <= p["youtube_units_per_day"]
    assert p["youtube_units_per_day"] <= s["youtube_units_per_day"]
    assert f["llm_tokens_per_day"] <= p["llm_tokens_per_day"]
    assert p["llm_tokens_per_day"] <= s["llm_tokens_per_day"]
    # document_count_cap: -1 means unlimited; treat that as infinity
    def _cap_to_int(n: int) -> float:
        return float("inf") if n == -1 else float(n)
    assert _cap_to_int(f["document_count_cap"]) <= _cap_to_int(p["document_count_cap"])
    assert _cap_to_int(p["document_count_cap"]) <= _cap_to_int(s["document_count_cap"])


def test_features_are_supersets_with_tier():
    f, p, s = (
        TIER_CAPABILITIES[Tier.FREE]["features"],
        TIER_CAPABILITIES[Tier.PRO]["features"],
        TIER_CAPABILITIES[Tier.STUDIO]["features"],
    )
    assert f.issubset(p)
    assert p.issubset(s)


def test_capabilities_for_returns_tier_dict():
    assert capabilities_for(_make_user("free")) is TIER_CAPABILITIES[Tier.FREE]
    assert capabilities_for(_make_user("studio")) is TIER_CAPABILITIES[Tier.STUDIO]


# ---------------------------------------------------------------------------
# Feature checks
# ---------------------------------------------------------------------------


def test_has_feature_basic_qa_on_every_tier():
    for tier_value in ("free", "pro", "studio"):
        assert has_feature(_make_user(tier_value), "library_qa")


def test_author_studio_only_on_pro_and_above():
    assert not has_feature(_make_user("free"), "author_studio")
    assert has_feature(_make_user("pro"), "author_studio")
    assert has_feature(_make_user("studio"), "author_studio")


def test_byok_llm_keys_only_on_studio():
    assert not has_feature(_make_user("free"), "byok_llm_keys")
    assert not has_feature(_make_user("pro"), "byok_llm_keys")
    assert has_feature(_make_user("studio"), "byok_llm_keys")


def test_unknown_feature_is_falsy():
    assert not has_feature(_make_user("studio"), "feature_does_not_exist")


# ---------------------------------------------------------------------------
# Quota lookup
# ---------------------------------------------------------------------------


def test_quota_limit_returns_int():
    n = quota_limit(_make_user("free"), "youtube_units_per_day")
    assert isinstance(n, int)
    assert n > 0


def test_unlimited_quota_returns_minus_one():
    assert quota_limit(_make_user("studio"), "document_count_cap") == -1


# ---------------------------------------------------------------------------
# FastAPI dependencies — require_tier / require_feature
# ---------------------------------------------------------------------------


def _build_app_with_dep(dep) -> TestClient:
    """Build a tiny FastAPI app with one route guarded by `dep`, using
    the project's real `get_current_user` flow (so the test exercises
    auth + tier check end-to-end)."""
    from app.dependencies import get_db
    from app.main import app as _real_app  # noqa: F401  (ensures app is importable)

    test_app = FastAPI()
    router = APIRouter()

    @router.get("/api/v1/_test/gated")
    def gated(_: User = Depends(dep)):
        return {"ok": True}

    test_app.include_router(router)
    return test_app


@pytest.fixture
def gated_client(db):
    """Client with a single endpoint requiring PRO tier."""
    test_app = _build_app_with_dep(require_tier(Tier.PRO))
    from app.dependencies import get_db
    test_app.dependency_overrides[get_db] = lambda: db
    return TestClient(test_app)


def test_require_tier_passes_when_user_meets_min(gated_client, db):
    pro_user = auth_service.create_user(db, email="pro@x.com", password="x" * 12)
    pro_user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(pro_user.id)
    r = gated_client.get(
        "/api/v1/_test/gated",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_require_tier_403_when_user_below_min(gated_client, db):
    free_user = auth_service.create_user(db, email="free@x.com", password="x" * 12)
    # tier defaults to "free"
    token, _ = auth_service.create_access_token(free_user.id)
    r = gated_client.get(
        "/api/v1/_test/gated",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert "pro" in r.json()["detail"].lower()


def test_require_tier_passes_for_higher_tier(gated_client, db):
    studio_user = auth_service.create_user(db, email="studio@x.com", password="x" * 12)
    studio_user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(studio_user.id)
    r = gated_client.get(
        "/api/v1/_test/gated",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200


def test_require_feature_403_when_feature_missing(db):
    """`require_feature` raises 403 when the user's tier doesn't grant
    the feature — path independent of `require_tier`."""
    test_app = _build_app_with_dep(require_feature("byok_llm_keys"))
    from app.dependencies import get_db
    test_app.dependency_overrides[get_db] = lambda: db
    client = TestClient(test_app)

    pro_user = auth_service.create_user(db, email="pro2@x.com", password="x" * 12)
    pro_user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(pro_user.id)
    r = client.get(
        "/api/v1/_test/gated",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert "byok_llm_keys" in r.json()["detail"]


def test_require_feature_passes_when_feature_present(db):
    test_app = _build_app_with_dep(require_feature("author_studio"))
    from app.dependencies import get_db
    test_app.dependency_overrides[get_db] = lambda: db
    client = TestClient(test_app)

    pro_user = auth_service.create_user(db, email="pro3@x.com", password="x" * 12)
    pro_user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(pro_user.id)
    r = client.get(
        "/api/v1/_test/gated",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# User model integration
# ---------------------------------------------------------------------------


def test_new_user_defaults_to_free_tier(db):
    user = auth_service.create_user(db, email="new@x.com", password="x" * 12)
    assert user.tier == "free"
    assert get_user_tier(user) is Tier.FREE


def test_user_tier_can_be_upgraded_in_place(db):
    user = auth_service.create_user(db, email="upgrade@x.com", password="x" * 12)
    user.tier = "pro"
    db.commit()
    db.refresh(user)
    assert user.tier == "pro"
    assert get_user_tier(user) is Tier.PRO
