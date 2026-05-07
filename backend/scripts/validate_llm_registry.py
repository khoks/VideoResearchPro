"""Validate the LLM registry against the live provider — T-4.9.4.

Run this script periodically (manually or via a scheduled task) to
detect drift in `app/services/llm_routing.py::USE_CASE_REGISTRY`
*before* it surfaces at the next boot's health probe.

For each unique ``(provider, model)`` pair in the registry:
1. Resolves provider credentials from ``settings``.
2. Calls the provider's "list models" API.
3. Reports whether the model name in the registry actually exists.

OpenAI is the only provider with a cheap ``models.list()`` endpoint
that's exercised here. Anthropic / Google would need more involved
calls (Anthropic's `/v1/models` is recent; Google's `models.list` is
roundabout). Skipped when the API key for a provider isn't set —
prints a notice so the operator knows the check was incomplete.

Usage:
    cd backend
    ./venv/Scripts/python scripts/validate_llm_registry.py
    ./venv/Scripts/python scripts/validate_llm_registry.py --strict   # exit 1 on any miss

Exit code:
- 0 — all reachable models valid (or skipped because credentials unset)
- 1 — at least one model name doesn't resolve on a configured provider
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

# Allow running as a plain script: `python scripts/validate_llm_registry.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.llm_routing import USE_CASE_REGISTRY, resolve_config  # noqa: E402


def _unique_provider_model_pairs() -> list[tuple[str, str, list[str]]]:
    """Return ``[(provider, model, [use_cases_using_it]), ...]`` after
    resolving the effective config (env overrides applied)."""
    by_pair: dict[tuple[str, str], list[str]] = defaultdict(list)
    for use_case in USE_CASE_REGISTRY:
        cfg = resolve_config(use_case)
        by_pair[(cfg.provider, cfg.model)].append(use_case)
    return [
        (provider, model, sorted(use_cases))
        for (provider, model), use_cases in sorted(by_pair.items())
    ]


def _list_openai_models() -> set[str]:
    if not settings.OPENAI_API_KEY:
        return set()
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        return {m.id for m in client.models.list().data}
    except Exception as e:
        print(f"  ! OpenAI models.list() failed: {e}")
        return set()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on any model that doesn't resolve.",
    )
    args = parser.parse_args(argv)

    pairs = _unique_provider_model_pairs()
    print(f"Validating {len(pairs)} unique (provider, model) pairs:")

    # Per-provider available-model sets — one fetch each, reused across pairs.
    available_by_provider: dict[str, set[str]] = {}
    if any(p == "openai" for p, _, _ in pairs):
        available_by_provider["openai"] = _list_openai_models()

    failures = 0
    skipped = 0
    for provider, model, use_cases in pairs:
        available = available_by_provider.get(provider)
        if available is None:
            print(f"  ?  {provider}:{model}  — provider validation not implemented yet")
            print(f"     used by: {len(use_cases)} use case(s)")
            skipped += 1
            continue
        if not available:
            print(f"  -  {provider}:{model}  — credentials unset, skipped")
            print(f"     used by: {len(use_cases)} use case(s)")
            skipped += 1
            continue
        if model in available:
            print(f"  OK  {provider}:{model}")
        else:
            failures += 1
            print(f"  FAIL  {provider}:{model}  -- NOT in {provider}'s model list")
            print(f"     used by {len(use_cases)} use case(s): {use_cases[:5]}{'...' if len(use_cases) > 5 else ''}")
            # Suggest near-matches.
            close = sorted(m for m in available if model.split("-")[0] in m)
            if close:
                print(f"     near matches: {close[:6]}")

    print()
    print(f"Summary: {len(pairs) - failures - skipped} valid, {failures} failed, {skipped} skipped")

    if args.strict and failures > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
