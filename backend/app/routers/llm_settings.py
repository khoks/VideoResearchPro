"""Per-user LLM settings + cost calculator — E-1.13.

GET    /api/v1/settings/llm            — use cases, defaults, overrides, model options
PUT    /api/v1/settings/llm/{use_case} — set the caller's override
DELETE /api/v1/settings/llm/{use_case} — clear the caller's override
POST   /api/v1/settings/llm/estimate   — benchmark cost estimate (with optional
                                          hypothetical overrides for previewing)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user_llm_override import UserLLMOverride
from app.services import llm_service
from app.services.cost_estimator import estimate
from app.services.llm_routing import (
    _VALID_PROVIDERS,
    _VALID_REASONING,
    MODEL_CONTEXT_WINDOWS,
    USE_CASE_REGISTRY,
    UseCaseConfig,
    context_window_for,
    resolve_config,
)
from app.services.model_pricing import MODEL_PRICING, PRICING_AS_OF, pricing_for

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings/llm", tags=["llm-settings"])

_GROUPS = {
    "qa_": "Job Q&A",
    "library_qa_": "Library Q&A",
    "qa_history_": "Q&A history chat",
    "knowledge_": "Knowledge extraction",
    "search_": "Topic search",
    "report_": "Report generation",
    "social_": "Social classification",
}


def _group_for(use_case: str) -> str:
    for prefix, label in _GROUPS.items():
        if use_case.startswith(prefix):
            return label
    return "Other"


def _provider_for_model(model: str) -> str:
    if model.startswith("gpt-") or model.startswith("o"):
        return "openai"
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith("gemini-"):
        return "google"
    return "local"


def _model_options() -> dict:
    """Selectable models per provider: union of the window registry and
    the pricing table, with window + pricing metadata."""
    providers: dict[str, dict] = {p: {"models": []} for p in ("openai", "anthropic", "google")}
    seen: set[str] = set()
    for model in list(MODEL_CONTEXT_WINDOWS) + list(MODEL_PRICING):
        if model in seen:
            continue
        seen.add(model)
        provider = _provider_for_model(model)
        if provider not in providers:
            continue
        p = pricing_for(model)
        providers[provider]["models"].append(
            {
                "id": model,
                "context_window": context_window_for(model),
                "input_per_m": p.input_per_m if p else None,
                "output_per_m": p.output_per_m if p else None,
                "pricing_note": p.note if p else "no published pricing",
            }
        )
    for p in providers.values():
        p["models"].sort(key=lambda m: m["id"])
    return providers


class OverridePayload(BaseModel):
    provider: str = Field(min_length=1, max_length=16)
    model: str = Field(min_length=1, max_length=128)
    reasoning: str = Field(default="off", max_length=16)


class EstimatePayload(BaseModel):
    overrides: dict[str, OverridePayload] = Field(default_factory=dict)


def _validate(payload: OverridePayload, use_case: str | None = None) -> None:
    if use_case is not None and use_case not in USE_CASE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown use case '{use_case}'")
    if payload.provider not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown provider '{payload.provider}'. Valid: {list(_VALID_PROVIDERS)}",
        )
    if payload.reasoning not in _VALID_REASONING:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown reasoning '{payload.reasoning}'. Valid: {list(_VALID_REASONING)}",
        )


@router.get("")
def get_llm_settings(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows = (
        db.query(UserLLMOverride)
        .filter(UserLLMOverride.user_id == current_user.id)
        .all()
    )
    overrides = {r.use_case: r for r in rows}

    use_cases = []
    with llm_service.byok_context(current_user.id, db):
        for use_case, info in USE_CASE_REGISTRY.items():
            o = overrides.get(use_case)
            effective = resolve_config(use_case)
            use_cases.append(
                {
                    "use_case": use_case,
                    "summary": info.summary,
                    "group": _group_for(use_case),
                    "default": {
                        "provider": info.default_config.provider,
                        "model": info.default_config.model,
                        "reasoning": info.default_config.reasoning,
                    },
                    "override": (
                        {"provider": o.provider, "model": o.model, "reasoning": o.reasoning}
                        if o
                        else None
                    ),
                    "effective": {
                        "provider": effective.provider,
                        "model": effective.model,
                        "reasoning": effective.reasoning,
                    },
                    "typical_input_tokens": info.typical_input_tokens,
                    "typical_output_tokens": info.typical_output_tokens,
                }
            )

    return {
        "use_cases": use_cases,
        "providers": _model_options(),
        "reasoning_levels": list(_VALID_REASONING),
        "pricing_as_of": PRICING_AS_OF,
    }


@router.put("/{use_case}")
def set_override(
    use_case: str,
    payload: OverridePayload,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _validate(payload, use_case)
    row = (
        db.query(UserLLMOverride)
        .filter(
            UserLLMOverride.user_id == current_user.id,
            UserLLMOverride.use_case == use_case,
        )
        .first()
    )
    if row is None:
        row = UserLLMOverride(
            user_id=current_user.id,
            use_case=use_case,
            provider=payload.provider,
            model=payload.model,
            reasoning=payload.reasoning,
        )
        db.add(row)
    else:
        row.provider = payload.provider
        row.model = payload.model
        row.reasoning = payload.reasoning
    db.commit()
    logger.info(
        "user %s override: %s -> %s:%s:%s",
        current_user.id, use_case, payload.provider, payload.model, payload.reasoning,
    )
    return {"saved": True}


@router.delete("/{use_case}")
def clear_override(
    use_case: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if use_case not in USE_CASE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown use case '{use_case}'")
    deleted = (
        db.query(UserLLMOverride)
        .filter(
            UserLLMOverride.user_id == current_user.id,
            UserLLMOverride.use_case == use_case,
        )
        .delete()
    )
    db.commit()
    return {"cleared": bool(deleted)}


@router.post("/estimate")
def estimate_cost(
    payload: EstimatePayload,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    for uc, p in payload.overrides.items():
        _validate(p, uc)
    hypothetical = {
        uc: UseCaseConfig(provider=p.provider, model=p.model, reasoning=p.reasoning)
        for uc, p in payload.overrides.items()
    }
    # Effective configs for non-overridden rows come from the user's saved
    # overrides via the byok/user context.
    with llm_service.byok_context(current_user.id, db):
        return estimate(hypothetical)
