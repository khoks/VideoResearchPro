"""Every prompt must still format, and must still carry its contracts.

This file exists because of a specific incident: a prompt edit left
`MAP_CHUNK_PROMPT.format()` raising `KeyError` for every batch. The map
loop caught the exception per batch, logged it, and continued — so the job
finished green, the report was composed from an empty extraction, and the
only visible symptom was that it was polite and said very little.

A missing placeholder is not a typo; it is a silent total failure of a
pipeline stage. These tests bind each prompt to the arguments its call site
actually passes, so the failure surfaces here instead of in a report nobody
can tell is empty.
"""
from __future__ import annotations

import ast
from pathlib import Path
from string import Formatter

import pytest

from app.agents.prompts.knowledge_prompts import EXTRACT_BATCH_PROMPT
from app.agents.prompts.qa_prompts import QA_SYSTEM_PROMPT
from app.agents.prompts.report_prompts import (
    COMPOSE_SECTION_PROMPT,
    COMPOSE_SUMMARY_PROMPT,
    MAP_CHUNK_PROMPT,
)
from app.agents.prompts.shared import (
    CODE_MIXING_NOTE,
    ENGLISH_OUTPUT_CONTRACT,
    QUOTE_RENDERING_RULES,
    TEMPORAL_AWARENESS,
    TEMPORAL_EXTRACTION_NOTE,
    VISUAL_ANNOTATION_CONTRACT,
)


def _placeholders(template: str) -> set[str]:
    """Field names a `str.format` template requires."""
    return {
        name
        for _lit, name, _spec, _conv in Formatter().parse(template)
        if name
    }


def _call_site_kwargs(module_path: Path, prompt_name: str) -> list[set[str]]:
    """Keyword names passed to every `<prompt_name>.format(...)` in a module.

    Parsed from the source rather than executed, so this works without
    building an LLM client or reaching the network.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    found: list[set[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "format"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == prompt_name):
            continue
        found.append({kw.arg for kw in node.keywords if kw.arg})
    return found


_AGENTS = Path(__file__).resolve().parents[2] / "app" / "agents"

# (prompt object, module that formats it, its name in that module)
_FORMATTED_PROMPTS = [
    (MAP_CHUNK_PROMPT, _AGENTS / "report_agent.py", "MAP_CHUNK_PROMPT"),
    (COMPOSE_SECTION_PROMPT, _AGENTS / "report_agent.py", "COMPOSE_SECTION_PROMPT"),
    (COMPOSE_SUMMARY_PROMPT, _AGENTS / "report_agent.py", "COMPOSE_SUMMARY_PROMPT"),
    (EXTRACT_BATCH_PROMPT, _AGENTS / "knowledge_agent.py", "EXTRACT_BATCH_PROMPT"),
]


@pytest.mark.parametrize(
    "prompt,module,name",
    _FORMATTED_PROMPTS,
    ids=[n for _p, _m, n in _FORMATTED_PROMPTS],
)
def test_call_site_supplies_every_placeholder_the_prompt_declares(prompt, module, name):
    """The exact incident this file exists for.

    A placeholder added to a prompt without a matching kwarg makes
    `.format()` raise for every call — and the map loop swallows per-batch
    exceptions by design, so the job completes with an empty extraction and
    no error anywhere the user can see.
    """
    required = _placeholders(prompt)
    call_sites = _call_site_kwargs(module, name)
    assert call_sites, f"no {name}.format(...) call found in {module.name}"
    for supplied in call_sites:
        missing = required - supplied
        assert not missing, f"{name} needs {sorted(missing)}, not passed by {module.name}"
        # The reverse direction is a weaker smell (a stale kwarg is
        # harmless at runtime) but it means the prompt and the call site
        # have drifted, so flag it too.
        assert not supplied - required, (
            f"{module.name} passes {sorted(supplied - required)} that {name} "
            "no longer declares"
        )


@pytest.mark.parametrize(
    "prompt,module,name",
    _FORMATTED_PROMPTS,
    ids=[n for _p, _m, n in _FORMATTED_PROMPTS],
)
def test_prompts_actually_format(prompt, module, name):
    """`.format()` must not raise. Literal `{{`/`}}` in a prompt's JSON
    examples correctly resolve to single braces, so surviving braces in the
    output are expected — the assertion is that the call completes."""
    filled = prompt.format(**{k: "X" for k in _placeholders(prompt)})
    assert filled


@pytest.mark.parametrize("prompt_name,prompt", [
    ("MAP_CHUNK_PROMPT", MAP_CHUNK_PROMPT),
    ("COMPOSE_SECTION_PROMPT", COMPOSE_SECTION_PROMPT),
    ("COMPOSE_SUMMARY_PROMPT", COMPOSE_SUMMARY_PROMPT),
    ("EXTRACT_BATCH_PROMPT", EXTRACT_BATCH_PROMPT),
])
def test_prompts_that_see_transcript_text_declare_the_visual_placeholder(
    prompt_name, prompt
):
    """These four all read text that can contain `[VISUAL @ ...]` spans."""
    assert "{visual_annotations}" in prompt, prompt_name


def test_qa_system_prompt_carries_the_visual_contract_inline():
    """QA_SYSTEM_PROMPT is composed at import time, not formatted per call —
    so the contract has to be baked in rather than passed."""
    assert "NOT spoken words" in QA_SYSTEM_PROMPT
    assert "on screen at" in QA_SYSTEM_PROMPT
