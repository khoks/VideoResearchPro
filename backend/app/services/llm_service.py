"""LLM client factory with provider-agnostic primary routing.

Two axes:

1. **Purpose** — each call site is either ``"primary"`` (slow, smart, usually
   paid API) or ``"fast"`` (cheap, often local). The decision lives in
   ``app.services.llm_routing`` — edit that file to change routing.

2. **Provider** — the *primary* client can be OpenAI, Anthropic, or Google,
   selected by ``LLM_PRIMARY_PROVIDER``. The *fast* client is always
   OpenAI-compatible (LM Studio, vLLM, Ollama, or OpenAI proper) because
   that's the lowest common denominator for local inference.

Call sites should prefer ``get_llm_for(use_case)`` — it looks up the route
from the registry, so flipping a decision never touches call-site code.
The legacy ``get_llm(purpose=...)`` is kept for back-compat.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import settings
from app.services.llm_routing import UseCase, resolve_route

logger = logging.getLogger(__name__)

# Cache the validated primary model name (OpenAI path only) so we don't
# retry the /models round-trip on every call.
_validated_model: str | None = None


# ---------------------------------------------------------------------------
# Low-level builders — one per provider.
# ---------------------------------------------------------------------------
def _build_openai(
    model: str,
    temperature: float,
    max_tokens: int | None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ChatOpenAI:
    """Build a ``ChatOpenAI`` client. Used for both OpenAI primary and every
    OpenAI-compatible fast server (LM Studio, vLLM, Ollama shim, etc.)."""
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key if api_key is not None else settings.OPENAI_API_KEY,
        "temperature": temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


# Back-compat alias for any external caller that imported the old name.
_build_llm = _build_openai


def _build_anthropic(
    model: str,
    temperature: float,
    max_tokens: int | None,
) -> BaseChatModel:
    """Build an Anthropic ``ChatAnthropic`` client (lazy import)."""
    try:
        from langchain_anthropic import ChatAnthropic  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "LLM_PRIMARY_PROVIDER=anthropic requires: "
            "pip install langchain-anthropic"
        ) from e
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "LLM_PRIMARY_PROVIDER=anthropic requires ANTHROPIC_API_KEY to be set."
        )
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": settings.ANTHROPIC_API_KEY,
        "temperature": temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return ChatAnthropic(**kwargs)


def _build_google(
    model: str,
    temperature: float,
    max_tokens: int | None,
) -> BaseChatModel:
    """Build a Google Gemini ``ChatGoogleGenerativeAI`` client (lazy import)."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "LLM_PRIMARY_PROVIDER=google requires: "
            "pip install langchain-google-genai"
        ) from e
    if not settings.GOOGLE_API_KEY:
        raise RuntimeError(
            "LLM_PRIMARY_PROVIDER=google requires GOOGLE_API_KEY to be set."
        )
    kwargs: dict[str, Any] = {
        "model": model,
        "google_api_key": settings.GOOGLE_API_KEY,
        "temperature": temperature,
    }
    if max_tokens:
        # Gemini uses `max_output_tokens`, not `max_tokens`.
        kwargs["max_output_tokens"] = max_tokens
    return ChatGoogleGenerativeAI(**kwargs)


# ---------------------------------------------------------------------------
# Purpose-level builders.
# ---------------------------------------------------------------------------
def _resolve_primary_model() -> str:
    """Resolve the primary model name, preferring LLM_PRIMARY_MODEL but
    falling back to the legacy LLM_MODEL for back-compat."""
    return settings.LLM_PRIMARY_MODEL or settings.LLM_MODEL


def _validate_openai_model(model: str) -> bool:
    """Verify the model is available on the OpenAI API.

    ``ChatOpenAI(model=...)`` does not validate the model name — it only
    fails on first ``.invoke()``. To detect a typo or unavailable model
    eagerly (so we can fall back), query the OpenAI models endpoint.
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        client.models.retrieve(model)
        return True
    except Exception as e:
        logger.warning("OpenAI model validation failed for %r: %s", model, e)
        return False


# Back-compat: tests monkeypatch this name.
_validate_model = _validate_openai_model


def _get_primary_llm(temperature: float, max_tokens: int | None) -> BaseChatModel:
    """Build the primary LLM, dispatching on ``LLM_PRIMARY_PROVIDER``.

    OpenAI path validates the model once and caches the result, falling
    back to ``LLM_FALLBACK_MODEL`` on failure. Anthropic / Google paths
    trust the configured model name — their APIs either return a clear
    error on invoke or succeed, so pre-validation buys little.
    """
    global _validated_model
    provider = settings.LLM_PRIMARY_PROVIDER

    if provider == "openai":
        if _validated_model:
            return _build_openai(_validated_model, temperature, max_tokens)
        primary = _resolve_primary_model()
        if _validate_model(primary):
            _validated_model = primary
            return _build_openai(primary, temperature, max_tokens)
        fallback = settings.LLM_FALLBACK_MODEL
        logger.warning(
            "LLM model %r unavailable on OpenAI. Falling back to %r.",
            primary, fallback,
        )
        _validated_model = fallback
        return _build_openai(fallback, temperature, max_tokens)

    if provider == "anthropic":
        return _build_anthropic(_resolve_primary_model(), temperature, max_tokens)

    if provider == "google":
        return _build_google(_resolve_primary_model(), temperature, max_tokens)

    raise ValueError(
        f"Unknown LLM_PRIMARY_PROVIDER={provider!r}. "
        f"Must be one of: openai, anthropic, google."
    )


def _get_fast_llm(temperature: float, max_tokens: int | None) -> BaseChatModel:
    """Build the fast LLM.

    If ``LLM_FAST_BASE_URL`` is set, route to that OpenAI-compatible server
    (e.g. LM Studio) using ``LLM_FAST_MODEL`` and ``LLM_FAST_API_KEY``. We
    intentionally skip ``_validate_openai_model`` here — local servers often
    don't implement ``/models`` reliably.

    If ``LLM_FAST_BASE_URL`` is unset, fall back to the normal OpenAI
    endpoint but still use the cheaper ``LLM_FAST_MODEL``, so the caller
    saves tokens even when no local server is configured.
    """
    if settings.LLM_FAST_BASE_URL:
        return _build_openai(
            settings.LLM_FAST_MODEL,
            temperature,
            max_tokens,
            base_url=settings.LLM_FAST_BASE_URL,
            api_key=settings.LLM_FAST_API_KEY or "not-needed",
        )
    return _build_openai(settings.LLM_FAST_MODEL, temperature, max_tokens)


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------
def get_llm(
    temperature: float = 0.0,
    max_tokens: int | None = None,
    *,
    purpose: Literal["primary", "fast"] = "primary",
) -> BaseChatModel:
    """Back-compat API. Prefer ``get_llm_for(use_case=...)`` in new code.

    ``purpose="primary"`` uses ``LLM_PRIMARY_PROVIDER`` + ``LLM_PRIMARY_MODEL``
    (falls back to ``LLM_MODEL``).

    ``purpose="fast"`` uses ``LLM_FAST_MODEL``, optionally against an
    OpenAI-compatible server at ``LLM_FAST_BASE_URL``.
    """
    if purpose == "fast":
        return _get_fast_llm(temperature, max_tokens)
    return _get_primary_llm(temperature, max_tokens)


def get_llm_for(
    use_case: UseCase,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """Build the LLM for a named call site.

    Looks up ``use_case`` in ``app.services.llm_routing.USE_CASE_REGISTRY``
    and routes to primary or fast based on the resolved route (which honors
    ``LLM_ROUTE_OVERRIDES``).

    This is the preferred call-site API. It makes the "which LLM handles
    this?" decision a single-place change instead of a codebase-wide
    grep-and-edit.
    """
    route = resolve_route(use_case)
    return get_llm(temperature=temperature, max_tokens=max_tokens, purpose=route)
