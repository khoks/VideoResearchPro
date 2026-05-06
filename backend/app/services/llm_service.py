"""LLM client factory with per-use-case provider + model + reasoning routing.

Three axes resolved per call:

1. **Use case** — a named call site (e.g. ``qa_formulate_answer``). The
   registry in ``app.services.llm_routing`` has one entry per call site
   with a ``default_config`` and rationale. Flip the decision via
   ``LLM_USE_CASE_CONFIG`` without touching code.

2. **Provider** — ``openai`` / ``anthropic`` / ``google`` (SaaS) or
   ``local`` (any OpenAI-compatible server: LM Studio, vLLM, Ollama,
   llama.cpp-server). Chosen per use case.

3. **Reasoning level** — ``off`` / ``minimal`` / ``low`` / ``medium`` /
   ``high`` / ``auto``. Normalized across providers:

   * OpenAI → ``reasoning_effort`` via ``model_kwargs``
   * Anthropic → ``thinking={"type": "enabled", "budget_tokens": N}``
   * Google → ``thinking_budget`` (integer tokens, or -1 for adaptive)

Call sites should use ``get_llm_for(use_case, ...)``. The legacy
``get_llm(purpose=...)`` shim is preserved for any remaining external
callers.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.config import settings
from app.services.llm_routing import (
    ReasoningLevel,
    UseCase,
    UseCaseConfig,
    resolve_config,
    resolve_route,
)

logger = logging.getLogger(__name__)

# T-5.6.4: BYOK call-site context. Router / Celery handlers set the
# (tenant_id, db_session) tuple once at the top of their scope; every
# `get_llm_for` call inside that scope picks them up automatically. This
# avoids threading kwargs through every agent / LangGraph node.
_byok_context: ContextVar[tuple[str | None, Any | None]] = ContextVar(
    "_byok_context", default=(None, None)
)


@contextmanager
def byok_context(
    tenant_id: str | None, db: Any | None
) -> Iterator[None]:
    """Set the BYOK lookup context for the duration of the with-block.

    Usage in a router::

        with llm_service.byok_context(current_user.id, db):
            answer, refs = run_qa_agent(...)

    Or in a Celery task::

        with SessionLocal() as db:
            job = job_service.get_job(db, job_id)
            with llm_service.byok_context(job.tenant_id, db):
                run_report_agent(...)

    The context resets automatically on with-block exit (and is safe
    against exceptions). Nested contexts work via ContextVar tokens.
    """
    token = _byok_context.set((tenant_id, db))
    try:
        yield
    finally:
        _byok_context.reset(token)

# Cache the validated primary model name (OpenAI back-compat path) so we
# don't retry the /models round-trip on every call. Cleared between tests
# by the autouse fixture in test_llm_service_routing.py.
_validated_model: str | None = None


# ---------------------------------------------------------------------------
# Reasoning parameter mapping (provider-agnostic → provider-specific)
# ---------------------------------------------------------------------------

# Anthropic maps reasoning levels to thinking budget tokens. Values are
# conservative; set LLM_USE_CASE_CONFIG with a concrete reasoning level
# if a specific call needs more or less headroom.
_ANTHROPIC_THINKING_BUDGET = {
    "minimal": 1_024,
    "low": 2_048,
    "medium": 4_096,
    "high": 16_384,
    # "auto" has no native analog on Claude; treat as medium.
    "auto": 4_096,
}

# Google maps reasoning levels to thinking budget tokens. "auto" uses -1
# to let the model decide (Gemini 2.5 adaptive thinking).
_GOOGLE_THINKING_BUDGET = {
    "off": 0,
    "minimal": 512,
    "low": 2_048,
    "medium": 8_192,
    "high": 16_384,
    "auto": -1,
}


def _openai_reasoning_kwargs(reasoning: ReasoningLevel) -> dict[str, Any]:
    """Translate reasoning level to OpenAI ``model_kwargs``.

    ``off`` emits no ``reasoning_effort`` (the model decides — typically
    fast). Any other level is passed through as-is; OpenAI accepts
    ``minimal`` / ``low`` / ``medium`` / ``high``. ``auto`` is mapped to
    ``medium`` because OpenAI has no adaptive knob today.
    """
    if reasoning == "off":
        return {}
    if reasoning == "auto":
        return {"model_kwargs": {"reasoning_effort": "medium"}}
    return {"model_kwargs": {"reasoning_effort": reasoning}}


def _anthropic_reasoning_kwargs(reasoning: ReasoningLevel) -> dict[str, Any]:
    if reasoning == "off":
        return {}
    budget = _ANTHROPIC_THINKING_BUDGET.get(reasoning, 4_096)
    return {"thinking": {"type": "enabled", "budget_tokens": budget}}


def _google_reasoning_kwargs(reasoning: ReasoningLevel) -> dict[str, Any]:
    # Google accepts thinking_budget even when "off" (value 0 disables it).
    # Pass through for every level so behavior is deterministic.
    budget = _GOOGLE_THINKING_BUDGET.get(reasoning, 0)
    return {"thinking_budget": budget}


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
    reasoning: ReasoningLevel = "off",
) -> ChatOpenAI:
    """Build a ``ChatOpenAI`` client. Used for both OpenAI primary and every
    OpenAI-compatible local server (LM Studio, vLLM, Ollama shim, etc.).

    Local servers generally don't implement reasoning params, so callers
    should pass ``reasoning="off"`` when ``base_url`` points at a local
    endpoint.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key if api_key is not None else settings.OPENAI_API_KEY,
        "temperature": temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if base_url:
        kwargs["base_url"] = base_url
    # Merge reasoning kwargs last so explicit caller-provided
    # model_kwargs (none today, but future-proof) are preserved.
    kwargs.update(_openai_reasoning_kwargs(reasoning))
    return ChatOpenAI(**kwargs)


# Back-compat alias for any external caller that imported the old name.
_build_llm = _build_openai


def _build_anthropic(
    model: str,
    temperature: float,
    max_tokens: int | None,
    *,
    api_key: str | None = None,
    reasoning: ReasoningLevel = "off",
) -> BaseChatModel:
    """Build an Anthropic ``ChatAnthropic`` client (lazy import)."""
    try:
        from langchain_anthropic import ChatAnthropic  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "provider=anthropic requires: pip install langchain-anthropic"
        ) from e
    effective_key = api_key if api_key is not None else settings.ANTHROPIC_API_KEY
    if not effective_key:
        raise RuntimeError(
            "provider=anthropic requires ANTHROPIC_API_KEY to be set "
            "(or a per-user BYOK credential via /api/v1/auth/credentials)."
        )
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": effective_key,
        "temperature": temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    kwargs.update(_anthropic_reasoning_kwargs(reasoning))
    return ChatAnthropic(**kwargs)


def _build_google(
    model: str,
    temperature: float,
    max_tokens: int | None,
    *,
    api_key: str | None = None,
    reasoning: ReasoningLevel = "off",
) -> BaseChatModel:
    """Build a Google Gemini ``ChatGoogleGenerativeAI`` client (lazy import)."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "provider=google requires: pip install langchain-google-genai"
        ) from e
    effective_key = api_key if api_key is not None else settings.GOOGLE_API_KEY
    if not effective_key:
        raise RuntimeError(
            "provider=google requires GOOGLE_API_KEY to be set "
            "(or a per-user BYOK credential via /api/v1/auth/credentials)."
        )
    kwargs: dict[str, Any] = {
        "model": model,
        "google_api_key": effective_key,
        "temperature": temperature,
    }
    if max_tokens:
        # Gemini uses `max_output_tokens`, not `max_tokens`.
        kwargs["max_output_tokens"] = max_tokens
    kwargs.update(_google_reasoning_kwargs(reasoning))
    return ChatGoogleGenerativeAI(**kwargs)


def _local_base_url() -> str | None:
    """Canonical local endpoint: ``LLM_LOCAL_BASE_URL`` first, legacy
    ``LLM_FAST_BASE_URL`` as fallback. Returns ``None`` if neither is set."""
    return (
        getattr(settings, "LLM_LOCAL_BASE_URL", "")
        or settings.LLM_FAST_BASE_URL
        or None
    )


def _local_api_key() -> str:
    """Canonical local API key (default ``not-needed`` — LM Studio ignores it
    but the OpenAI SDK rejects an empty string)."""
    return (
        getattr(settings, "LLM_LOCAL_API_KEY", "")
        or settings.LLM_FAST_API_KEY
        or "not-needed"
    )


# ---------------------------------------------------------------------------
# Config-driven builder (new canonical path)
# ---------------------------------------------------------------------------


def _build_from_config(
    cfg: UseCaseConfig,
    temperature: float,
    max_tokens: int | None,
    *,
    byok_api_key: str | None = None,
) -> BaseChatModel:
    """Build a chat client from a resolved ``UseCaseConfig``.

    T-5.6.4: ``byok_api_key`` overrides the install-wide env-var key for
    OpenAI / Anthropic / Google providers. The ``local`` provider ignores
    BYOK — local endpoints are install-wide infrastructure not eligible
    for per-user routing.
    """
    if cfg.provider == "local":
        base_url = _local_base_url()
        if not base_url:
            raise RuntimeError(
                "Use case resolved to provider=local but neither "
                "LLM_LOCAL_BASE_URL nor LLM_FAST_BASE_URL is set. Point "
                "one of them at your local OpenAI-compatible endpoint "
                "(e.g. http://localhost:1234/v1) or change the use-case "
                "provider via LLM_USE_CASE_CONFIG."
            )
        # Local servers generally don't implement reasoning_effort; pass
        # it through if the user asked for it, but don't force it on by
        # default — cfg.reasoning already defaults to 'off' per-registry
        # for use cases we ship with local defaults. BYOK ignored for
        # local — there's no per-user alternative endpoint.
        return _build_openai(
            cfg.model,
            temperature,
            max_tokens,
            base_url=base_url,
            api_key=_local_api_key(),
            reasoning=cfg.reasoning,
        )
    if cfg.provider == "openai":
        return _build_openai(
            cfg.model,
            temperature,
            max_tokens,
            api_key=byok_api_key,
            reasoning=cfg.reasoning,
        )
    if cfg.provider == "anthropic":
        return _build_anthropic(
            cfg.model,
            temperature,
            max_tokens,
            api_key=byok_api_key,
            reasoning=cfg.reasoning,
        )
    if cfg.provider == "google":
        return _build_google(
            cfg.model,
            temperature,
            max_tokens,
            api_key=byok_api_key,
            reasoning=cfg.reasoning,
        )
    raise ValueError(
        f"Unknown provider {cfg.provider!r} in UseCaseConfig. "
        f"Must be one of: openai, anthropic, google, local."
    )


def _resolve_byok_api_key(
    provider: str,
    tenant_id: str | None,
    db: Any | None,
) -> str | None:
    """Look up the BYOK credential for ``(tenant_id, provider)``, or
    return None if not applicable.

    Returns None when:
    - ``tenant_id`` is None (no user context — Celery startup probe, smoke check)
    - ``db`` is None (caller chose not to plumb a session — equivalent
      to opting out of BYOK)
    - The user has the ``byok_llm_keys`` feature OFF (Free / Pro tiers)
    - No credential is stored for this provider
    - The stored credential is undecryptable (key rotation; warn and
      fall back to env-var)
    - The provider is ``local`` (BYOK doesn't apply)
    """
    if tenant_id is None or db is None:
        return None
    if provider == "local":
        return None
    try:
        # Tier gate — only Studio gets BYOK. Free / Pro users could still
        # have rows in user_credentials from before a downgrade; we don't
        # honour them.
        from app.services import auth_service, byok_service
        from app.services.tier_service import has_feature

        user = auth_service.get_user_by_id(db, tenant_id)
        if user is None:
            return None
        if not has_feature(user, "byok_llm_keys"):
            return None
        return byok_service.get_credential(db, user_id=tenant_id, provider=provider)
    except Exception:
        logger.exception(
            "BYOK lookup failed for tenant_id=%s provider=%s — falling back "
            "to install-wide env-var key",
            tenant_id,
            provider,
        )
        return None


# ---------------------------------------------------------------------------
# Back-compat: purpose-level builders (primary/fast binary)
# ---------------------------------------------------------------------------
def _resolve_primary_model() -> str:
    """Primary model for the legacy ``purpose='primary'`` path. Prefers
    ``LLM_PRIMARY_MODEL`` and falls back to ``LLM_MODEL``."""
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
    """Legacy primary builder (back-compat for ``get_llm(purpose='primary')``).

    Dispatches on ``LLM_PRIMARY_PROVIDER``. OpenAI path validates + caches
    the model; others trust the configured name.
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
    """Legacy fast builder (back-compat for ``get_llm(purpose='fast')``).

    If a local endpoint is configured, route to it. Otherwise use
    ``LLM_FAST_MODEL`` against the default OpenAI endpoint.
    """
    base_url = _local_base_url()
    if base_url:
        return _build_openai(
            settings.LLM_FAST_MODEL,
            temperature,
            max_tokens,
            base_url=base_url,
            api_key=_local_api_key(),
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

    ``purpose="primary"`` uses ``LLM_PRIMARY_PROVIDER`` + ``LLM_PRIMARY_MODEL``.
    ``purpose="fast"`` uses ``LLM_FAST_MODEL`` at the local endpoint if
    configured.
    """
    if purpose == "fast":
        return _get_fast_llm(temperature, max_tokens)
    return _get_primary_llm(temperature, max_tokens)


def get_llm_for(
    use_case: UseCase,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    *,
    tenant_id: str | None = None,
    db: Any | None = None,
) -> BaseChatModel:
    """Build the LLM for a named call site.

    Resolves provider + model + reasoning from the registry (with env
    overrides applied) and builds the appropriate provider client. This
    is the canonical call-site API.

    T-5.6.4 BYOK integration: when both ``tenant_id`` AND ``db`` are
    passed (or available via ``byok_context(...)``), attempts to look up
    a per-user BYOK credential for the resolved provider. On hit, uses
    it; on miss / decrypt-error / non-Studio-tier user, falls back to
    the install-wide env-var key.

    The cleanest call shape is to set ``byok_context`` once at the
    router or Celery entry point and let every nested ``get_llm_for``
    call pick it up. Explicit params are still supported for tests.
    """
    cfg = resolve_config(use_case)

    # Resolve effective tenant + db from explicit args or context var.
    if tenant_id is None and db is None:
        ctx_tenant, ctx_db = _byok_context.get()
        tenant_id = ctx_tenant
        db = ctx_db
    elif (tenant_id is None) ^ (db is None):
        logger.warning(
            "get_llm_for: only one of (tenant_id, db) provided; BYOK "
            "lookup skipped. Both or neither must be passed (or use "
            "byok_context(...) at the call-site boundary)."
        )

    byok_api_key = _resolve_byok_api_key(cfg.provider, tenant_id, db)
    return _build_from_config(
        cfg, temperature, max_tokens, byok_api_key=byok_api_key
    )


# ---------------------------------------------------------------------------
# Probe helper for smoke checks and stress tests.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a trivial liveness probe against a ``UseCaseConfig``.

    ``ok=True`` means the provider responded with any non-empty content
    within the timeout. ``ok=False`` means it either raised, timed out,
    or returned empty.
    """

    config: UseCaseConfig
    ok: bool
    latency_ms: int
    error: str | None = None


def probe_config(
    cfg: UseCaseConfig,
    *,
    timeout_seconds: float = 10.0,
) -> ProbeResult:
    """Fire a one-token probe against ``cfg`` and return the outcome.

    Sync (not async) — called from the FastAPI lifespan via ``asyncio.to_thread``
    or from the stress-test CLI directly. Never raises; every failure is
    captured in ``ProbeResult.error``.
    """
    # Build the client first — build errors (missing API key, missing
    # pip package) are a legitimate probe failure reason.
    try:
        llm = _build_from_config(cfg, temperature=0.0, max_tokens=16)
    except Exception as e:
        return ProbeResult(
            config=cfg, ok=False, latency_ms=0, error=f"build: {e}"
        )
    # langchain clients don't uniformly expose a timeout kwarg on .invoke;
    # we rely on the provider SDK's default (usually 60s) and trust the
    # caller's wall-clock timeout. Providers that take longer than
    # timeout_seconds still count as "responded" if they eventually
    # succeed — the goal is "does it work at all", not "is it fast".
    start = time.monotonic()
    try:
        resp = llm.invoke([HumanMessage(content="Reply with the single word: ok")])
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ProbeResult(
            config=cfg, ok=False, latency_ms=elapsed_ms, error=str(e)[:300]
        )
    elapsed_ms = int((time.monotonic() - start) * 1000)
    content = getattr(resp, "content", "") or ""
    if not content.strip():
        return ProbeResult(
            config=cfg,
            ok=False,
            latency_ms=elapsed_ms,
            error="empty response content",
        )
    return ProbeResult(config=cfg, ok=True, latency_ms=elapsed_ms, error=None)


# Keep resolve_route importable from here for any external caller.
__all__ = [
    "get_llm",
    "get_llm_for",
    "probe_config",
    "ProbeResult",
    "resolve_route",
]
