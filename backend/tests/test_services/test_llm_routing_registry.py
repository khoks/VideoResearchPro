"""Tests for app.services.llm_routing — the use-case registry.

Guards:
  * Every ``UseCase`` Literal has a registry entry (and vice-versa).
  * ``resolve_route`` returns the registry default when no override is set.
  * ``LLM_ROUTE_OVERRIDES`` flips the route at runtime, tolerates whitespace,
    logs-and-ignores malformed / unknown entries, and doesn't crash.
  * Asking for an unknown use_case literal raises ``KeyError`` loudly (it's a
    programming error, not an operator error).
"""
from __future__ import annotations

import typing

import pytest

from app.services import llm_routing


def test_every_use_case_literal_has_a_registry_entry() -> None:
    """The ``UseCase`` Literal and ``USE_CASE_REGISTRY`` must stay in sync."""
    literal_names = set(typing.get_args(llm_routing.UseCase))
    registry_names = set(llm_routing.USE_CASE_REGISTRY.keys())

    missing_from_registry = literal_names - registry_names
    missing_from_literal = registry_names - literal_names

    assert not missing_from_registry, (
        f"UseCase literals missing from USE_CASE_REGISTRY: {missing_from_registry}"
    )
    assert not missing_from_literal, (
        f"Registry entries missing from UseCase literal: {missing_from_literal}"
    )


def test_registry_entries_have_coherent_metadata() -> None:
    """Each entry's default_route is valid and its token fields are sane."""
    for name, info in llm_routing.USE_CASE_REGISTRY.items():
        assert info.default_route in ("primary", "fast"), (
            f"{name}: invalid default_route {info.default_route!r}"
        )
        assert info.typical_input_tokens >= 0, name
        assert info.p95_input_tokens >= info.typical_input_tokens, (
            f"{name}: p95 ({info.p95_input_tokens}) < typical "
            f"({info.typical_input_tokens})"
        )
        assert info.typical_output_tokens >= 0, name
        assert info.min_context_recommended >= 1024, name
        assert info.summary.strip(), f"{name}: empty summary"
        assert info.rationale.strip(), f"{name}: empty rationale"


def _expected_route_from_config(info: llm_routing.UseCaseInfo) -> llm_routing.Route:
    """Compute the route resolve_route() should return for a given entry's
    default config, given the post-LLM_USE_CASE_CONFIG semantics:
    "fast" only when provider resolves to "local"; everything else is "primary".

    This is the source of truth for "what does the resolver actually do?" —
    `info.default_route` is documentation of the *intent* (cheap call site)
    and may legitimately differ from what resolve_route returns when the
    cheap call site uses a SaaS provider rather than the local one.
    """
    return "fast" if info.default_config.provider == "local" else "primary"


def test_resolve_route_returns_registry_default_when_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_routing.settings, "LLM_ROUTE_OVERRIDES", "")
    monkeypatch.setattr(llm_routing.settings, "LLM_USE_CASE_CONFIG", "")

    for name, info in llm_routing.USE_CASE_REGISTRY.items():
        assert llm_routing.resolve_route(name) == _expected_route_from_config(info)


def test_resolve_route_honors_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """An override flips a single use case without touching others."""
    monkeypatch.setattr(llm_routing.settings, "LLM_USE_CASE_CONFIG", "")

    # Pick a registry entry that resolves to "primary" so we can flip it to
    # "fast" and see the change.
    primary_default = next(
        n for n, i in llm_routing.USE_CASE_REGISTRY.items()
        if _expected_route_from_config(i) == "primary"
    )
    monkeypatch.setattr(
        llm_routing.settings,
        "LLM_ROUTE_OVERRIDES",
        f"{primary_default}=fast",
    )

    assert llm_routing.resolve_route(primary_default) == "fast"

    # Other entries are unchanged.
    for name, info in llm_routing.USE_CASE_REGISTRY.items():
        if name == primary_default:
            continue
        assert llm_routing.resolve_route(name) == _expected_route_from_config(info)


def test_resolve_route_override_tolerates_whitespace_and_casing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm_routing.settings,
        "LLM_ROUTE_OVERRIDES",
        "  qa_clarification = PRIMARY  ,  qa_refine_context=FAST  ",
    )

    assert llm_routing.resolve_route("qa_clarification") == "primary"
    assert llm_routing.resolve_route("qa_refine_context") == "fast"


def test_resolve_route_ignores_unknown_or_malformed_overrides(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Typos in the env var must not crash resolve_route."""
    monkeypatch.setattr(llm_routing.settings, "LLM_USE_CASE_CONFIG", "")
    monkeypatch.setattr(
        llm_routing.settings,
        "LLM_ROUTE_OVERRIDES",
        "not_a_use_case=fast,qa_clarification=bogus,missing_equals,qa_refine_context=primary",
    )

    # Valid override still applied.
    assert llm_routing.resolve_route("qa_refine_context") == "primary"

    # Invalid route for a real use case → falls back to the route that
    # resolve_route would derive from the registry's default_config.
    assert (
        llm_routing.resolve_route("qa_clarification")
        == _expected_route_from_config(
            llm_routing.USE_CASE_REGISTRY["qa_clarification"]
        )
    )


def test_resolve_route_raises_on_unknown_use_case() -> None:
    with pytest.raises(KeyError):
        llm_routing.resolve_route("this_does_not_exist")  # type: ignore[arg-type]


def test_describe_registry_contains_every_entry() -> None:
    out = llm_routing.describe_registry()
    for name in llm_routing.USE_CASE_REGISTRY:
        assert name in out
