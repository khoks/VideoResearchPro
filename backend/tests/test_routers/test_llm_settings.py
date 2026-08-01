"""E-1.13 — per-user LLM overrides + cost calculator tests."""
from app.models.user_llm_override import UserLLMOverride
from app.services import llm_service
from app.services.llm_routing import UseCaseConfig, resolve_config


def test_get_llm_settings_shape(client, test_user):
    r = client.get("/api/v1/settings/llm")
    assert r.status_code == 200
    d = r.json()
    # Bound to the registry rather than a literal: a hardcoded count turns
    # every new use case into a spurious failure in an unrelated test.
    from app.services.llm_routing import USE_CASE_REGISTRY

    assert len(d["use_cases"]) == len(USE_CASE_REGISTRY)
    row = next(u for u in d["use_cases"] if u["use_case"] == "qa_formulate_answer")
    assert row["override"] is None
    assert row["default"]["provider"] in ("openai", "anthropic")
    assert "openai" in d["providers"] and "google" in d["providers"]
    assert any(m["id"].startswith("gemini-") for m in d["providers"]["google"]["models"])
    assert "off" in d["reasoning_levels"]


def test_put_and_delete_override(client, test_user, db):
    r = client.put(
        "/api/v1/settings/llm/qa_formulate_answer",
        json={"provider": "openai", "model": "gpt-5.6-luna", "reasoning": "off"},
    )
    assert r.status_code == 200
    row = db.query(UserLLMOverride).filter_by(user_id=test_user.id).first()
    assert row.model == "gpt-5.6-luna"

    d = client.get("/api/v1/settings/llm").json()
    uc = next(u for u in d["use_cases"] if u["use_case"] == "qa_formulate_answer")
    assert uc["override"]["model"] == "gpt-5.6-luna"
    assert uc["effective"]["model"] == "gpt-5.6-luna"

    r = client.delete("/api/v1/settings/llm/qa_formulate_answer")
    assert r.status_code == 200
    assert db.query(UserLLMOverride).filter_by(user_id=test_user.id).count() == 0


def test_put_rejects_bad_provider_and_use_case(client, test_user):
    assert client.put(
        "/api/v1/settings/llm/qa_formulate_answer",
        json={"provider": "closedai", "model": "x", "reasoning": "off"},
    ).status_code == 422
    assert client.put(
        "/api/v1/settings/llm/nope",
        json={"provider": "openai", "model": "x", "reasoning": "off"},
    ).status_code == 404


def test_override_layers_into_resolve_config(client, test_user, db):
    client.put(
        "/api/v1/settings/llm/report_map_chunks",
        json={"provider": "google", "model": "gemini-2.5-flash-lite", "reasoning": "off"},
    )
    with llm_service.byok_context(test_user.id, db):
        cfg = resolve_config("report_map_chunks")
        assert cfg == UseCaseConfig("google", "gemini-2.5-flash-lite", "off")
    # Outside the context: default again.
    assert resolve_config("report_map_chunks").provider == "openai"


def test_estimate_endpoint_defaults(client, test_user):
    r = client.post("/api/v1/settings/llm/estimate", json={"overrides": {}})
    assert r.status_code == 200
    d = r.json()
    assert d["benchmark"]["videos"] == 200
    assert d["totals"]["cost_usd"] > 0
    map_row = next(u for u in d["per_use_case"] if u["use_case"] == "report_map_chunks")
    assert map_row["calls"] >= 6  # 1.34M corpus / <=120K budget


def test_estimate_reacts_to_hypothetical_override(client, test_user):
    base = client.post("/api/v1/settings/llm/estimate", json={"overrides": {}}).json()
    pricier = client.post(
        "/api/v1/settings/llm/estimate",
        json={"overrides": {"report_map_chunks": {"provider": "openai", "model": "gpt-5.5-pro", "reasoning": "off"}}},
    ).json()
    assert pricier["totals"]["cost_usd"] > base["totals"]["cost_usd"]


def test_estimate_unknown_pricing_model_flagged(client, test_user):
    d = client.post(
        "/api/v1/settings/llm/estimate",
        json={"overrides": {"report_map_chunks": {"provider": "local", "model": "qwen/qwen3-9b", "reasoning": "off"}}},
    ).json()
    assert "qwen/qwen3-9b" in d["totals"]["unknown_pricing_models"]
    row = next(u for u in d["per_use_case"] if u["use_case"] == "report_map_chunks")
    assert row["pricing_known"] is False


def test_settings_require_auth(unauthenticated_client):
    assert unauthenticated_client.get("/api/v1/settings/llm").status_code == 401
    assert unauthenticated_client.put(
        "/api/v1/settings/llm/qa_formulate_answer",
        json={"provider": "openai", "model": "x", "reasoning": "off"},
    ).status_code == 401
