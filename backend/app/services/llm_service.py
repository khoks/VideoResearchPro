from langchain_openai import ChatOpenAI

from app.config import settings


def get_llm(temperature: float = 0.0, max_tokens: int | None = None) -> ChatOpenAI:
    """Get the configured LLM instance."""
    kwargs = {
        "model": settings.LLM_MODEL,
        "api_key": settings.OPENAI_API_KEY,
        "temperature": temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs)
