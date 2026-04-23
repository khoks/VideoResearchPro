import logging
from typing import Literal

from langchain_openai import ChatOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# Cache the validated primary model name so we don't retry fallback on every
# call. The fast path skips validation entirely (LM Studio and similar
# OpenAI-compatible servers don't reliably implement /models).
_validated_model: str | None = None


def _build_llm(
    model: str,
    temperature: float,
    max_tokens: int | None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ChatOpenAI:
    kwargs: dict = {
        "model": model,
        "api_key": api_key if api_key is not None else settings.OPENAI_API_KEY,
        "temperature": temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def _validate_model(model: str) -> bool:
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
        logger.warning("Model validation failed for %r: %s", model, e)
        return False


def _get_primary_llm(temperature: float, max_tokens: int | None) -> ChatOpenAI:
    """Build the primary OpenAI LLM, falling back to LLM_FALLBACK_MODEL if needed."""
    global _validated_model

    if _validated_model:
        return _build_llm(_validated_model, temperature, max_tokens)

    primary = settings.LLM_MODEL
    if _validate_model(primary):
        _validated_model = primary
        return _build_llm(primary, temperature, max_tokens)

    fallback = settings.LLM_FALLBACK_MODEL
    logger.warning(
        "LLM model %r unavailable. Falling back to %r.", primary, fallback,
    )
    _validated_model = fallback
    return _build_llm(fallback, temperature, max_tokens)


def _get_fast_llm(temperature: float, max_tokens: int | None) -> ChatOpenAI:
    """Build the fast LLM.

    If ``LLM_FAST_BASE_URL`` is set, route to that OpenAI-compatible server
    (e.g. LM Studio) using ``LLM_FAST_MODEL`` and ``LLM_FAST_API_KEY``. We
    intentionally skip ``_validate_model`` here — local servers often don't
    implement ``/models`` reliably.

    If ``LLM_FAST_BASE_URL`` is unset, fall back to the normal OpenAI endpoint
    but still use the cheaper ``LLM_FAST_MODEL``, so the caller saves tokens
    even when no local server is configured.
    """
    if settings.LLM_FAST_BASE_URL:
        return _build_llm(
            settings.LLM_FAST_MODEL,
            temperature,
            max_tokens,
            base_url=settings.LLM_FAST_BASE_URL,
            api_key=settings.LLM_FAST_API_KEY or "not-needed",
        )
    return _build_llm(settings.LLM_FAST_MODEL, temperature, max_tokens)


def get_llm(
    temperature: float = 0.0,
    max_tokens: int | None = None,
    *,
    purpose: Literal["primary", "fast"] = "primary",
) -> ChatOpenAI:
    """Get the configured LLM instance.

    ``purpose="primary"`` (default) uses the high-quality ``LLM_MODEL`` on
    OpenAI (with fallback to ``LLM_FALLBACK_MODEL`` if validation fails).

    ``purpose="fast"`` uses ``LLM_FAST_MODEL``. When ``LLM_FAST_BASE_URL`` is
    set, the fast client is pointed at that OpenAI-compatible server
    (typically a local LM Studio instance); otherwise it runs against OpenAI
    with a cheaper model. The fast path skips model validation.
    """
    if purpose == "fast":
        return _get_fast_llm(temperature, max_tokens)
    return _get_primary_llm(temperature, max_tokens)
