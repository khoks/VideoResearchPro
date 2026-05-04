"""Tests for the /api/v1/health* endpoints.

Guards:
  * ``/health`` still exposes the basic liveness contract (``status`` +
    ``app``) and now also surfaces the LLM smoke-probe summary.
  * ``/health/llm`` returns the full per-use-case breakdown (``summary`` +
    ``use_cases``).
  * When ``_STATUS`` is empty the LLM status is ``"unknown"``; after a
    successful probe-result fixture it's ``"ok"``; a failed use case
    flips it to ``"degraded"``.
"""
from __future__ import annotations

import pytest

from app.services import llm_smoke


@pytest.fixture
def reset_llm_status():
    """Isolate the process-global _STATUS so tests don't leak into each other."""
    llm_smoke._STATUS.reset()
    yield
    llm_smoke._STATUS.reset()


def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "Pratidhvani"


def test_health_check_includes_llm_status(client, reset_llm_status):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "llm" in data
    assert "status" in data["llm"]
    # With no probes run the status should be "unknown" -- app is still usable.
    assert data["llm"]["status"] == "unknown"


def test_health_check_includes_capabilities(client):
    """Per S-1.5.9, surface opt-in capability flags so the frontend
    can decide which UI surfaces to expose without inspecting env
    state directly."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    caps = response.json().get("capabilities") or {}
    # All four capability flags should be present (booleans).
    assert isinstance(caps.get("twitter_search_enabled"), bool)
    assert isinstance(caps.get("article_search_enabled"), bool)
    assert isinstance(caps.get("playwright_fallback_enabled"), bool)
    assert isinstance(caps.get("whisper_transcribe_enabled"), bool)


def test_health_capabilities_reflect_settings(client, monkeypatch):
    """When env-vars flip, the capability flags should follow."""
    from app.routers import health as _health

    monkeypatch.setattr(_health.settings, "TWITTER_BEARER_TOKEN", "set")
    monkeypatch.setattr(_health.settings, "BRAVE_SEARCH_API_KEY", "")
    monkeypatch.setattr(_health.settings, "ARTICLE_PLAYWRIGHT_ENABLED", True)
    monkeypatch.setattr(_health.settings, "OPENAI_API_KEY", "set")

    response = client.get("/api/v1/health")
    caps = response.json()["capabilities"]
    assert caps["twitter_search_enabled"] is True
    assert caps["article_search_enabled"] is False
    assert caps["playwright_fallback_enabled"] is True
    assert caps["whisper_transcribe_enabled"] is True


def test_health_llm_endpoint_returns_summary_and_use_cases(
    client, reset_llm_status
):
    response = client.get("/api/v1/health/llm")
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "use_cases" in data
    assert data["summary"]["status"] == "unknown"
    assert data["use_cases"] == {}


def test_health_llm_reports_ok_when_all_use_cases_succeed(
    client, reset_llm_status
):
    all_use_cases = {
        uc for ucs in llm_smoke.FEATURE_TO_USE_CASES.values() for uc in ucs
    }
    llm_smoke._STATUS.set_results([
        llm_smoke.UseCaseStatus(
            use_case=uc, provider="openai", model="gpt-5.4-mini",
            reasoning="off", ok=True, latency_ms=5, error=None,
        )
        for uc in all_use_cases
    ])

    response = client.get("/api/v1/health/llm")
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["status"] == "ok"
    assert data["summary"]["unavailable_features"] == []
    assert set(data["use_cases"].keys()) == all_use_cases


def test_health_llm_reports_degraded_when_one_feature_fails(
    client, reset_llm_status
):
    all_use_cases = {
        uc for ucs in llm_smoke.FEATURE_TO_USE_CASES.values() for uc in ucs
    }
    llm_smoke._STATUS.set_results([
        llm_smoke.UseCaseStatus(
            use_case=uc, provider="openai", model="gpt-5.4-mini",
            reasoning="off",
            ok=(uc != "qa_formulate_answer"),
            latency_ms=5,
            error=None if uc != "qa_formulate_answer" else "boom",
        )
        for uc in all_use_cases
    ])

    # Full endpoint reports degraded + lists the failing feature.
    response = client.get("/api/v1/health/llm")
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["status"] == "degraded"
    assert "qa" in data["summary"]["unavailable_features"]

    # Summary inside /health mirrors it.
    summary_response = client.get("/api/v1/health")
    assert summary_response.json()["llm"]["status"] == "degraded"
