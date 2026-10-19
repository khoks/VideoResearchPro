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
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from unittest.mock import MagicMock, patch

import pytest

from app.agents import qa_agent, report_agent
from app.agents.prompts.knowledge_prompts import (
    EXTRACT_BATCH_PROMPT,
    SYNTHESIZE_REPORT_PROMPT,
)
from app.agents.prompts.qa_prompts import (
    LIBRARY_QA_ANSWER_PROMPT,
    LIBRARY_QA_SYSTEM_PROMPT,
    LIBRARY_REFINE_CONTEXT_PROMPT,
    QA_ANSWER_PROMPT,
    QA_SYSTEM_PROMPT,
    REFINE_CONTEXT_PROMPT,
)
from app.agents.prompts.report_prompts import (
    CHANNEL_MAP_PROMPT,
    COMPOSE_SECTION_PROMPT,
    COMPOSE_SUMMARY_PROMPT,
    MAP_CHUNK_PROMPT,
)
from app.agents.prompts.search_prompts import (
    PLAN_SEARCHES_PROMPT,
    RANK_AND_CURATE_PROMPT,
)
from app.agents.prompts.temporal_prompts import TEMPORAL_SCOPE_PROMPT
from app.agents.prompts.shared import (
    CODE_MIXING_NOTE,
    ENGLISH_OUTPUT_CONTRACT,
    QUOTE_RENDERING_RULES,
    TEMPORAL_AWARENESS,
    TEMPORAL_EXTRACTION_NOTE,
    VISUAL_ANNOTATION_CONTRACT,
    VISUAL_SPAN_EXTRACT_RULE,
)
from app.services.visual_service import annotate_segments, strip_annotations
from app.utils.chunking import chunk_transcript


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
_SERVICES = Path(__file__).resolve().parents[2] / "app" / "services"

# (prompt object, module that formats it, its name in that module)
_FORMATTED_PROMPTS = [
    (MAP_CHUNK_PROMPT, _AGENTS / "report_agent.py", "MAP_CHUNK_PROMPT"),
    (COMPOSE_SECTION_PROMPT, _AGENTS / "report_agent.py", "COMPOSE_SECTION_PROMPT"),
    (COMPOSE_SUMMARY_PROMPT, _AGENTS / "report_agent.py", "COMPOSE_SUMMARY_PROMPT"),
    (EXTRACT_BATCH_PROMPT, _AGENTS / "knowledge_agent.py", "EXTRACT_BATCH_PROMPT"),
    (SYNTHESIZE_REPORT_PROMPT, _AGENTS / "knowledge_agent.py", "SYNTHESIZE_REPORT_PROMPT"),
    # R3 / S-1.15.2 batch (2026-10-18): the prompts that batch touched.
    (QA_ANSWER_PROMPT, _AGENTS / "qa_agent.py", "QA_ANSWER_PROMPT"),
    (LIBRARY_QA_ANSWER_PROMPT, _AGENTS / "qa_agent.py", "LIBRARY_QA_ANSWER_PROMPT"),
    (LIBRARY_QA_SYSTEM_PROMPT, _AGENTS / "qa_agent.py", "LIBRARY_QA_SYSTEM_PROMPT"),
    (PLAN_SEARCHES_PROMPT, _AGENTS / "search_agent.py", "PLAN_SEARCHES_PROMPT"),
    (RANK_AND_CURATE_PROMPT, _AGENTS / "search_agent.py", "RANK_AND_CURATE_PROMPT"),
    (TEMPORAL_SCOPE_PROMPT, _SERVICES / "temporal_service.py", "TEMPORAL_SCOPE_PROMPT"),
    # T-1.18.1.12 / .13 (2026-10-19): three more transcript readers.
    (CHANNEL_MAP_PROMPT, _AGENTS / "report_agent.py", "CHANNEL_MAP_PROMPT"),
    (REFINE_CONTEXT_PROMPT, _AGENTS / "qa_agent.py", "REFINE_CONTEXT_PROMPT"),
    (LIBRARY_REFINE_CONTEXT_PROMPT, _AGENTS / "qa_agent.py", "LIBRARY_REFINE_CONTEXT_PROMPT"),
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
    ("CHANNEL_MAP_PROMPT", CHANNEL_MAP_PROMPT),
    ("REFINE_CONTEXT_PROMPT", REFINE_CONTEXT_PROMPT),
    ("LIBRARY_REFINE_CONTEXT_PROMPT", LIBRARY_REFINE_CONTEXT_PROMPT),
])
def test_prompts_that_see_transcript_text_declare_the_visual_placeholder(
    prompt_name, prompt
):
    """These all read text that can contain `[VISUAL @ ...]` spans."""
    assert "{visual_annotations}" in prompt, prompt_name


def test_qa_system_prompt_carries_the_visual_contract_inline():
    """QA_SYSTEM_PROMPT is composed at import time, not formatted per call —
    so the contract has to be baked in rather than passed."""
    assert "NOT spoken words" in QA_SYSTEM_PROMPT
    assert "on screen at" in QA_SYSTEM_PROMPT


def test_library_qa_system_prompt_carries_time_and_visual_contracts():
    """Composed at import time like QA_SYSTEM_PROMPT; it reads transcript-
    derived context, so it needs both contracts baked in (R3 / R1)."""
    assert "SUPERSESSION" in LIBRARY_QA_SYSTEM_PROMPT
    assert "NOT spoken words" in LIBRARY_QA_SYSTEM_PROMPT
    assert "SUPERSESSION" in QA_SYSTEM_PROMPT


def test_temporal_fragments_state_the_r3_contract():
    assert "true AS OF" in TEMPORAL_AWARENESS
    assert "SUPERSESSION" in TEMPORAL_AWARENESS
    assert "Anchor RELATIVE time" in TEMPORAL_EXTRACTION_NOTE
    assert "discusses <era>" in TEMPORAL_EXTRACTION_NOTE


# ---------------------------------------------------------------------------
# S-1.18.6: the speaker-attribution boundary (D-071)
# ---------------------------------------------------------------------------
#
# The R1 measurement (docs/notes/2026-10-18-r1-visual-measurement.md) found
# two sentences that credited a named speaker with a detail that existed only
# in a `[VISUAL @ mm:ss — ...]` span. The contract forbade reading spans AS
# speech but said nothing about mixing the two inside one attributed clause.
# The rule is stated once, in shared.py, and reaches every prompt that reads
# transcript text through the same fragment — these tests pin both halves.

_ATTRIBUTION_RULE_HEAD = "ATTRIBUTION BOUNDARY"
_ATTRIBUTION_RULE_CORE = "ONLY what that speaker said"


def test_attribution_boundary_rule_is_stated_once_in_the_contract():
    assert VISUAL_ANNOTATION_CONTRACT.count(_ATTRIBUTION_RULE_HEAD) == 1
    # Speech-only inside an attributed sentence ...
    assert _ATTRIBUTION_RULE_CORE in VISUAL_ANNOTATION_CONTRACT
    # ... the screen-only detail in its own clause, marked as shown ...
    assert "separate clause marked as shown on screen" in VISUAL_ANNOTATION_CONTRACT
    # ... and the pattern the sweep judged correct every time stays allowed.
    assert '"also visible on screen" stays correct' in VISUAL_ANNOTATION_CONTRACT


def _composed(prompt: str) -> str:
    """Fill a prompt the way its call site does: the visual contract in its
    placeholder, a dummy for everything else. Import-time prompts (the two
    Q&A system prompts) carry the contract baked in."""
    kwargs = {k: "X" for k in _placeholders(prompt)}
    if "visual_annotations" in kwargs:
        kwargs["visual_annotations"] = VISUAL_ANNOTATION_CONTRACT
    return prompt.format(**kwargs) if kwargs else prompt


@pytest.mark.parametrize("prompt_name,prompt", [
    ("MAP_CHUNK_PROMPT", MAP_CHUNK_PROMPT),
    ("COMPOSE_SECTION_PROMPT", COMPOSE_SECTION_PROMPT),
    ("COMPOSE_SUMMARY_PROMPT", COMPOSE_SUMMARY_PROMPT),
    ("EXTRACT_BATCH_PROMPT", EXTRACT_BATCH_PROMPT),
    ("QA_SYSTEM_PROMPT", QA_SYSTEM_PROMPT),
    ("LIBRARY_QA_SYSTEM_PROMPT", LIBRARY_QA_SYSTEM_PROMPT),
    ("CHANNEL_MAP_PROMPT", CHANNEL_MAP_PROMPT),
    ("REFINE_CONTEXT_PROMPT", REFINE_CONTEXT_PROMPT),
    ("LIBRARY_REFINE_CONTEXT_PROMPT", LIBRARY_REFINE_CONTEXT_PROMPT),
])
def test_every_prompt_that_reads_transcript_text_carries_the_rule_once(
    prompt_name, prompt
):
    """Exactly once: zero means a prompt lost the contract; two means a
    prompt file re-stated it by hand, which is how rules drift."""
    composed = _composed(prompt)
    assert composed.count(_ATTRIBUTION_RULE_HEAD) == 1, prompt_name
    assert _ATTRIBUTION_RULE_CORE in composed, prompt_name


@dataclass
class _Frame:
    timestamp_seconds: float
    description: str
    informative: bool = True
    status: str = "described"


def test_map_prompt_shows_the_model_speech_and_span_with_the_rule_in_force():
    """The D-071 shape, end to end up to the model boundary.

    Speech and span disagree: the speaker names two variables and a fitted
    line; only the frame shows a confidence band. The transcript goes through
    the production merge (`annotate_segments`) and chunker, then the report
    map stage with a stubbed LLM. The prompt that reaches the model must
    carry the speech, the span intact, and the rule — and the screen-only
    detail must exist NOWHERE in that prompt outside the span, so the test
    is the real case and not a speech/span agreement in disguise.
    """
    speech = (
        "This regression plot shows two numerical variables with a fitted "
        "regression line through them."
    )
    # Worded differently from the rule's own example, which also mentions a
    # confidence band — otherwise the "nowhere outside the span" check below
    # would trip on the contract text itself.
    screen_only = "shaded 95 percent confidence band"
    description = f"seaborn regplot: scatter, fitted line, {screen_only}"
    segments = [
        {"text": speech, "start": 621.0, "duration": 6.0},
        {"text": "Next we change the colour palette.", "start": 627.0, "duration": 4.0},
    ]
    annotated = annotate_segments(segments, [_Frame(621.0, description)])
    chunks = chunk_transcript(
        annotated,
        chunk_size=256,
        chunk_overlap=32,
        video_metadata={
            "video_id": "v1",
            "title": "Seaborn regplot walkthrough",
            "channel_name": "ChA",
            "channel_id": "UC_ChA",
            "url": "https://www.youtube.com/watch?v=v1",
        },
    )
    assert chunks, "chunker produced nothing"

    response = MagicMock()
    response.content = (
        '{"facts": [], "comments": [], "conclusions": [], '
        '"references": [], "speakers": []}'
    )
    llm = MagicMock()
    llm.invoke.return_value = response
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        report_agent.map_chunks(
            {"job_type": "topic", "transcript_chunks": chunks, "topic": "seaborn tutorials"}
        )

    assert llm.invoke.call_count == 1, "a two-segment transcript is one map batch"
    prompt = llm.invoke.call_args.args[0][0].content

    # The speech reached the model.
    assert speech in prompt
    # The span reached the model intact: marker, timestamp, description.
    assert f"[VISUAL @ 10:21 — {description}]" in prompt
    # The screen-only detail exists only inside a span: strip the spans and
    # it is gone from everything the model sees.
    assert screen_only in prompt
    assert screen_only not in strip_annotations(prompt)
    # And the rule is in force in the same prompt.
    assert prompt.count(_ATTRIBUTION_RULE_HEAD) == 1
    assert _ATTRIBUTION_RULE_CORE in prompt
    # The rule did not displace the contracts that were already there.
    assert "LANGUAGE OF OUTPUT" in prompt
    assert "Anchor RELATIVE time" in prompt


# --- T-1.18.1.12 / .13: the two remaining transcript readers ---------------

_SPAN = "[VISUAL @ 10:21 — seaborn regplot: scatter, fitted line, shaded 95 percent confidence band]"


def _annotated_chunk(channel: str = "ChA") -> dict:
    return {
        "text": f"This regression plot shows two numerical variables. {_SPAN} Next we change the palette.",
        "timestamp_display": "10:21",
        "metadata": {
            "video_id": "v1", "video_title": "Seaborn regplot walkthrough",
            "channel_name": channel, "timestamp_start": 621.0,
        },
    }


def _stub_llm(content: str) -> MagicMock:
    response = MagicMock()
    response.content = content
    llm = MagicMock()
    llm.invoke.return_value = response
    return llm


def test_channel_map_prompt_receives_the_span_with_the_contract():
    """A channel job that opts into visual analysis gets annotated chunks
    (`_with_visuals` never checks job type); its map prompt had no contract."""
    llm = _stub_llm('{"channel_name": "ChA", "themes": [], "highlights": []}')
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        report_agent.compose_channel_report(
            {"job_type": "channel", "transcript_chunks": [_annotated_chunk()], "statistics": {}}
        )
    map_prompt = llm.invoke.call_args_list[0].args[0][0].content
    assert _SPAN in map_prompt
    assert map_prompt.count(_ATTRIBUTION_RULE_HEAD) == 1


@pytest.mark.parametrize("which", ["job", "library"])
def test_refine_prompt_tells_the_model_to_keep_spans_marked(which):
    """The refine step rewrites chunks before the answer prompt applies its
    contract, so a span it paraphrases into prose reaches the answer as speech."""
    llm = _stub_llm("extracts")
    chunk = {**_annotated_chunk(), "distance": 0.1}
    with patch.object(qa_agent, "get_llm_for", return_value=llm):
        if which == "job":
            qa_agent.refine_context({"question": "what does the plot show?", "rag_results": [chunk]})
            prompt = llm.invoke.call_args.args[0][0].content
        else:
            prompt = qa_agent.LIBRARY_REFINE_CONTEXT_PROMPT.format(
                question="q", raw_context=chunk["text"], visual_annotations=qa_agent.REFINE_VISUAL_RULES,
            )
    assert _SPAN in prompt
    assert VISUAL_SPAN_EXTRACT_RULE in prompt
    assert prompt.count(_ATTRIBUTION_RULE_HEAD) == 1

