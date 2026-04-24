"""Back-compat shim — delegates to ``stress_test_llm.py --provider=local``.

The real harness is ``stress_test_llm.py``; this entry point is kept so
older docs, shell aliases, and muscle memory keep working. It forwards
every argument (including ``--help``) verbatim after pinning the
provider to ``local`` and defaulting the model to ``LLM_FAST_MODEL``
when the caller doesn't supply one.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script: `python scripts/stress_test_local_llm.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.stress_test_llm import main  # noqa: E402


def _inject_local_defaults(argv: list[str]) -> list[str]:
    """Force ``--provider=local`` and default ``--model`` from settings.

    Preserves explicit user flags (including explicit ``--model`` / an
    explicit ``--use-case``). When the caller asks for ``--help`` we
    pass through untouched so argparse prints the full help text.
    """
    if any(a in ("-h", "--help") for a in argv):
        return argv

    out = list(argv)
    has_provider = any(a == "--provider" or a.startswith("--provider=") for a in out)
    has_use_case = any(a == "--use-case" or a.startswith("--use-case=") for a in out)
    has_model = any(a == "--model" or a.startswith("--model=") for a in out)

    if not has_provider and not has_use_case:
        out.insert(0, "--provider=local")
        if not has_model:
            from app.config import settings
            fallback_model = settings.LLM_FAST_MODEL or "local-model"
            out.insert(1, f"--model={fallback_model}")
    return out


if __name__ == "__main__":
    sys.exit(main(_inject_local_defaults(sys.argv[1:])))
