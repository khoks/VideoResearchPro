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
from app.services import llm_routing
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

    E-1.13: this is also the load point for the user's per-use-case LLM
    overrides — every user-scoped LLM entry point already brackets with
    this context manager (D-041), so piggybacking here gives override
    coverage everywhere BYOK is already correct. Load failures degrade
    to defaults (never break the wrapped work).
    """
    token = _byok_context.set((tenant_id, db))
    override_token = None
    if tenant_id is not None and db is not None:
        try:
            override_token = llm_routing.user_override_context.set(
                _load_user_overrides(tenant_id, db)
            )
        except Exception:
            logger.exception(
                "Failed to load user LLM overrides for %s; using defaults",
                tenant_id,
            )
    try:
        yield
    finally:
        if override_token is not None:
            llm_routing.user_override_context.reset(override_token)
        _byok_context.reset(token)


def _load_user_overrides(user_id: str, db: Any) -> dict | None:
    """Load ``user_llm_overrides`` rows into a use_case->config map."""
    from app.models.user_llm_override import UserLLMOverride

    rows = (
        db.query(UserLLMOverride)
        .filter(UserLLMOverride.user_id == user_id)
        .all()
    )
    if not rows:
        return None
    overrides: dict = {}
    for r in rows:
        if r.use_case not in llm_routing.USE_CASE_REGISTRY:
            continue  # stale row for a renamed use case — ignore
        overrides[r.use_case] = llm_routing.UseCaseConfig(
            provider=r.provider, model=r.model, reasoning=r.reasoning
        )
    return overrides or None

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


def _openai_reasoning_kwargs(reasoning: ReasoningLevel, model: str = "") -> dict[str, Any]:
    """Translate reasoning level to OpenAI ``model_kwargs``.

    D-054 research findings (2026-07-29):
    - gpt-5.x models reason ADAPTIVELY: an omitted ``reasoning_effort``
      defaults to *medium* (measured: 89 hidden reasoning tokens on a
      trivial prompt on gpt-5.5) — so ``off`` must send an explicit
      ``"none"`` on the 5.x family to genuinely disable thinking.
      Pre-5.x models (gpt-4.1*) predate the param; ``off`` still omits.
    - ``minimal`` was removed from the valid enum on gpt-5.5/5.6
      ("Supported values: none, low, medium, high, xhigh") — remapped to
      ``low`` universally.
    - ``auto`` maps to ``medium`` (OpenAI's adaptive router then decides
      per request how much of that ceiling to use).
    """
    if reasoning == "off":
        if model.startswith("gpt-5"):
            return {"model_kwargs": {"reasoning_effort": "none"}}
        return {}
    if reasoning == "minimal":
        return {"model_kwargs": {"reasoning_effort": "low"}}
    if reasoning == "auto":
        return {"model_kwargs": {"reasoning_effort": "medium"}}
    return {"model_kwargs": {"reasoning_effort": reasoning}}


# Claude 5-generation models use adaptive thinking + output_config.effort;
# the enabled+budget_tokens shape 400s on them ("not supported for this
# model") — D-053 live-probe catch. Older Claude models keep the legacy shape.
_ANTHROPIC_ADAPTIVE_THINKING_PREFIXES = (
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-haiku-5",
)

_ANTHROPIC_EFFORT_MAP = {
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "auto": "medium",
}


def _anthropic_reasoning_kwargs(reasoning: ReasoningLevel, model: str = "") -> dict[str, Any]:
    if reasoning == "off":
        return {}
    if model.startswith(_ANTHROPIC_ADAPTIVE_THINKING_PREFIXES):
        effort = _ANTHROPIC_EFFORT_MAP.get(reasoning, "medium")
        return {
            "thinking": {"type": "adaptive"},
            "model_kwargs": {"output_config": {"effort": effort}},
        }
    budget = _ANTHROPIC_THINKING_BUDGET.get(reasoning, 4_096)
    return {"thinking": {"type": "enabled", "budget_tokens": budget}}


_GOOGLE_THINKING_LEVEL = {
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "auto": "medium",
}


def _google_reasoning_kwargs(reasoning: ReasoningLevel, model: str = "") -> dict[str, Any]:
    # Gemini 3.x replaced the integer thinking_budget with thinking_level
    # (low/medium/high); the two cannot be combined. Measured matrix
    # (paid-tier bench 2026-07-29, D-054 amendments):
    #   * lite tiers don't think by default, but reject thinking_budget=0
    #     (400) — "off" must OMIT the config entirely.
    #   * 3.5-flash accepts thinking_budget=0 — a true disable.
    #   * 3.6-flash and 3.x Pro cannot disable thinking (budget=0 and
    #     level=minimal both 400; "low" is the floor). Omitting the config
    #     triggers DYNAMIC thinking that spends MORE than explicit high
    #     (628 vs 473 thoughts on the same prompt), so "off" pins "low".
    if model.startswith("gemini-3"):
        if reasoning == "off":
            if "flash-lite" in model:
                return {}
            if model.startswith("gemini-3.5-flash"):
                return {"thinking_budget": 0}
            return {"thinking_level": "low"}
        return {"thinking_level": _GOOGLE_THINKING_LEVEL.get(reasoning, "medium")}
    # Gemini 2.x and earlier: thinking_budget for every level (0 disables).
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
    # Local endpoints never get reasoning params (see docstring).
    kwargs.update(
        _openai_reasoning_kwargs(reasoning, model if not base_url else "")
    )
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
    reasoning_kwargs = _anthropic_reasoning_kwargs(reasoning, model)
    # Anthropic API constraint: `temperature` may only be 1 when extended
    # thinking is enabled. Callers pass temperature=0.0 for determinism —
    # with thinking on, the thinking budget IS the determinism control, so
    # we honor the constraint rather than 400 (D-053 live-probe catch).
    effective_temperature = 1.0 if reasoning_kwargs else temperature
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": effective_key,
        "temperature": effective_temperature,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    kwargs.update(reasoning_kwargs)
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
    reasoning_kwargs = _google_reasoning_kwargs(reasoning, model)
    kwargs.update(reasoning_kwargs)
    try:
        return ChatGoogleGenerativeAI(**kwargs)
    except (TypeError, ValueError) as e:
        # Older langchain-google-genai releases predate thinking_level
        # (Gemini 3.x). Degrade to no thinking config rather than failing
        # the whole call — reasoning becomes provider-default.
        if not reasoning_kwargs:
            raise
        logger.warning(
            "ChatGoogleGenerativeAI rejected reasoning kwargs %s (%s); "
            "retrying without them — upgrade langchain-google-genai to "
            "control Gemini 3.x thinking.",
            reasoning_kwargs,
            e,
        )
        for k in reasoning_kwargs:
            kwargs.pop(k, None)
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
# Response text extraction
# ---------------------------------------------------------------------------
def response_text(response) -> str:
    """Extract the assistant's TEXT from a chat response.

    Reasoning-capable providers return a LIST of content blocks rather than a
    string once the model actually thinks — Anthropic emits
    ``[{"type": "thinking", ...}, {"type": "text", "text": ...}]``. The shape
    is decided per request (adaptive reasoning), so the same use case returns
    a plain string for an easy prompt and a block list for a hard one; every
    call site reading ``.content`` directly would silently get a list exactly
    when the work was substantial.

    Thinking/redacted blocks are dropped — they are the model's scratchpad,
    never user-facing output and never valid JSON for the parsing call sites.
    """
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") in ("thinking", "redacted_thinking"):
                    continue
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return "" if content is None else str(content)


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


# A 16x16 solid-grey PNG, base64. The payload for vision probes: the only
# thing that proves a model accepts image parts is sending one. Deliberately
# tiny — image tokens scale with pixel count and this runs on every startup.
#
# Generated and verified with an independent decoder (ffprobe reports
# `png,16,16,gray`), not written from memory. The first attempt at this
# constant was plausible-looking but malformed, and OpenAI rejected it with
# `image_parse_error` — which would have made every vision probe report the
# model as unreachable. `test_probe_image_is_a_valid_png` pins the bytes.
_PROBE_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAAAAAA6mKC9AAAAD0lEQVR4nGNoQAMM"
    "I1sAAAUMgAFaSOXNAAAAAElFTkSuQmCC"
)


def probe_config(
    cfg: UseCaseConfig,
    *,
    timeout_seconds: float = 10.0,
    vision: bool = False,
) -> ProbeResult:
    """Fire a one-token probe against ``cfg`` and return the outcome.

    Sync (not async) — called from the FastAPI lifespan via ``asyncio.to_thread``
    or from the stress-test CLI directly. Never raises; every failure is
    captured in ``ProbeResult.error``.

    T-4.9.5: ``max_tokens`` is set to 256 when the use case has a
    non-``off`` reasoning effort. Reasoning models consume the budget on
    internal thinking before producing visible output, so a tight
    budget (16 tokens) yields a 400 "max_tokens reached" error before
    the model can emit even "ok". Non-reasoning configs keep the
    minimal 16-token budget — keeps probes cheap.

    ``vision=True`` (R1) attaches a 16x16 image to the probe. Required for
    multimodal use cases: a text-only probe against a text-only model
    succeeds, so without this a `visual_describe_frame` misconfigured onto
    a non-vision model would report healthy at startup and fail on the
    first real frame.
    """
    # Reasoning configs need a much larger budget — the internal-
    # thinking phase consumes tokens before any visible output.
    is_reasoning = cfg.reasoning != "off"
    probe_max_tokens = 256 if is_reasoning else 16

    # Build the client first — build errors (missing API key, missing
    # pip package) are a legitimate probe failure reason.
    try:
        llm = _build_from_config(cfg, temperature=0.0, max_tokens=probe_max_tokens)
    except Exception as e:
        return ProbeResult(
            config=cfg, ok=False, latency_ms=0, error=f"build: {e}"
        )
    # langchain clients don't uniformly expose a timeout kwarg on .invoke;
    # we rely on the provider SDK's default (usually 60s) and trust the
    # caller's wall-clock timeout. Providers that take longer than
    # timeout_seconds still count as "responded" if they eventually
    # succeed — the goal is "does it work at all", not "is it fast".
    if vision:
        probe_content: Any = [
            {"type": "text", "text": "Reply with the single word: ok"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{_PROBE_IMAGE_B64}"},
            },
        ]
    else:
        probe_content = "Reply with the single word: ok"

    start = time.monotonic()
    try:
        resp = llm.invoke([HumanMessage(content=probe_content)])
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ProbeResult(
            config=cfg, ok=False, latency_ms=elapsed_ms, error=str(e)[:300]
        )
    elapsed_ms = int((time.monotonic() - start) * 1000)
    # `response_text` rather than `.content` — reasoning configs return a
    # LIST of content blocks, and `list.strip()` would raise out of a
    # function documented as never raising.
    content = response_text(resp)
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
    "response_text",
    "get_llm",
    "get_llm_for",
    "probe_config",
    "ProbeResult",
    "resolve_route",
]
