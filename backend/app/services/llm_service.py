import logging

from langchain_openai import ChatOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# Cache the validated model name so we don't retry the fallback on every call
_validated_model: str | None = None


def _build_llm(model: str, temperature: float, max_tokens: int | None) -> ChatOpenAI:
    kwargs = {
        "model": model,
        "api_key": settings.OPENAI_API_KEY,
        "temperature": temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs)


def get_llm(temperature: float = 0.0, max_tokens: int | None = None) -> ChatOpenAI:
    """Get the configured LLM instance.

    If the configured ``LLM_MODEL`` is unavailable, fall back to
    ``LLM_FALLBACK_MODEL`` and log a warning. The successful model name is
    cached for subsequent calls to avoid repeated failure attempts.
    """
    global _validated_model

    if _validated_model:
        return _build_llm(_validated_model, temperature, max_tokens)

    primary = settings.LLM_MODEL
    try:
        llm = _build_llm(primary, temperature, max_tokens)
        _validated_model = primary
        return llm
    except Exception as e:
        fallback = settings.LLM_FALLBACK_MODEL
        logger.warning(
            "LLM model '%s' unavailable (%s). Falling back to '%s'.",
            primary, e, fallback,
        )
        llm = _build_llm(fallback, temperature, max_tokens)
        _validated_model = fallback
        return llm
