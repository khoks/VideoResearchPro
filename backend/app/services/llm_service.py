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


def get_llm(temperature: float = 0.0, max_tokens: int | None = None) -> ChatOpenAI:
    """Get the configured LLM instance.

    If the configured ``LLM_MODEL`` is unavailable (typo or not authorized
    on the API key), fall back to ``LLM_FALLBACK_MODEL`` and log a warning.
    The successful model name is cached so subsequent calls skip validation.
    """
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
