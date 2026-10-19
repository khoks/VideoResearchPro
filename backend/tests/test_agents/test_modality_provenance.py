"""S-1.18.8 / D-075: whether a fact was SAID or SHOWN is decided at the map
stage, survives the lossless reduce, and reaches the composer as a tag.

The motivating evidence: four of the five attribution errors confirmed after
the S-1.18.6 prompt rule sat in the one Bengali-language video, where the
composer could not read the speech. The map stage reads one chunk of native
speech at a time, so that is where the label is fixed. No real providers:
every LLM here is a stub.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from app.agents import report_agent
from app.agents.prompts.report_prompts import COMPOSE_SECTION_PROMPT, MAP_CHUNK_PROMPT
from app.agents.prompts.shared import (
    MODALITY_FIELD_RULE,
    MODALITY_TAGS_NOTE,
    VISUAL_ANNOTATION_CONTRACT,
)
from app.services.visual_service import annotate_segments
from app.utils.chunking import chunk_transcript

URL = "https://www.youtube.com/watch?v=bn1"
TITLE = "Seaborn tutorial in Bengali"

# Bengali speech with a version number in native digits (the D-075 case:
# "০.১৩.২" was spoken, and the composer claimed the screen displayed it).
SPOKEN = "আমরা সিবর্ন ভার্সন ০.১৩.২ ব্যবহার করছি।"
SHOWN_ONLY = "a ValueError traceback ending in 'could not convert string to float'"


@dataclass
class _Frame:
    timestamp_seconds: float
    description: str
    informative: bool = True
    status: str = "described"


def _chunks(with_frame: bool) -> list[dict]:
    segments = [
        {"text": SPOKEN, "start": 190.0, "duration": 6.0},
        {"text": "এখন আমরা প্লট বানাবো।", "start": 196.0, "duration": 5.0},
    ]
    if with_frame:
        segments = annotate_segments(segments, [_Frame(192.0, SHOWN_ONLY)])
    return chunk_transcript(
        segments, chunk_size=256, chunk_overlap=32,
        video_metadata={
            "video_id": "bn1", "title": TITLE, "channel_name": "CodeWithMunnaX",
            "url": URL, "published_at": "2025-06-01T00:00:00Z",
        },
    )


def _item(content: str, modality, ts: float = 190.0, **extra) -> dict:
    item = {
        "content": content, "video_title": TITLE, "channel_name": "CodeWithMunnaX",
        "timestamp_display": "3:10", "timestamp_seconds": ts,
        "video_url": f"{URL}&t={int(ts)}", "speaker": "presenter",
    }
    if modality is not None:
        item["modality"] = modality
    item.update(extra)
    return item


# The three cases the story names: spoken only, shown only, both.
MODEL_OUTPUT = {
    "facts": [
        _item("The presenter uses seaborn version 0.13.2.", "said"),
        _item("A ValueError traceback says a string could not be converted to float.", "shown", 192.0),
        _item("A scatter plot of the two columns is drawn.", "both", 196.0),
    ],
    "comments": [], "conclusions": [], "references": [], "speakers": [],
}


def _map(chunks: list[dict], payload: dict) -> tuple[dict, str, dict]:
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        out = report_agent.map_chunks({"job_type": "topic", "topic": "seaborn", "transcript_chunks": chunks})
    prompt = llm.invoke.call_args.args[0][0].content
    return out["chunk_summaries"][0], prompt, out["processing_notes"]


# ---------- map stage --------------------------------------------------------

def test_map_keeps_said_shown_both_for_a_source_with_frames():
    summary, prompt, notes = _map(_chunks(with_frame=True), MODEL_OUTPUT)
    assert [f["modality"] for f in summary["facts"]] == ["said", "shown", "both"]
    assert not any("modality_model" in f for f in summary["facts"])
    assert notes["map_modality"] == {"both": 1, "said": 1, "shown": 1}

    # What the model was shown: the native speech and the span, intact,
    # with the labelling rule and the converse rule in force.
    assert SPOKEN in prompt
    assert f"[VISUAL @ 3:12 — {SHOWN_ONLY}]" in prompt
    assert prompt.count("EVIDENCE MODALITY") == 1
    assert '"said"  — only in the spoken transcript' in prompt
    assert "CONVERSE:" in prompt


def test_map_forces_said_for_a_source_without_frames():
    """Nothing was on screen for a 'shown' label to come from."""
    summary, _prompt, notes = _map(_chunks(with_frame=False), MODEL_OUTPUT)
    assert [f["modality"] for f in summary["facts"]] == ["said", "said", "said"]
    # The model's own label survives for the audit record (S-1.14.6).
    assert [f.get("modality_model") for f in summary["facts"]] == [None, "shown", "both"]
    assert notes["map_modality"] == {"forced_said": 2, "said": 3}


def test_map_normalises_synonyms_and_marks_missing_as_unknown():
    payload = {
        "facts": [
            _item("spoken synonym", "Spoken"),
            _item("screen synonym", "on-screen"),
            _item("no label", None),
            _item("nonsense label", "telepathy"),
        ],
        "comments": [], "conclusions": [], "references": [], "speakers": [],
    }
    summary, _p, _n = _map(_chunks(with_frame=True), payload)
    assert [f["modality"] for f in summary["facts"]] == ["said", "shown", "unknown", "unknown"]
    assert summary["facts"][3]["modality_model"] == "telepathy"


def test_map_item_without_source_falls_back_to_the_batch():
    payload = {"facts": [{"content": "orphan", "modality": "shown"}],
               "comments": [], "conclusions": [], "references": [], "speakers": []}
    with_span, _p, _n = _map(_chunks(with_frame=True), payload)
    assert with_span["facts"][0]["modality"] == "shown"
    without, _p, _n = _map(_chunks(with_frame=False), payload)
    assert without["facts"][0]["modality"] == "said"


def test_unparsed_map_output_never_reaches_labelling_or_reduce():
    # S-1.14.19: non-JSON is a failed batch (retried in halves, then
    # dropped and disclosed), not a {"raw": ...} summary to label.
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="not json")
    chunks = _chunks(True)
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        out = report_agent.map_chunks({"job_type": "topic", "topic": "t", "transcript_chunks": chunks})
    assert out["chunk_summaries"] == []
    assert out["processing_notes"]["map_chunks_dropped"] == len(chunks)
    assert out["processing_notes"]["map_modality"] == {}


# ---------- reduce ------------------------------------------------------------

def test_reduce_preserves_every_label():
    a = {k: [] for k in report_agent._REDUCE_KEYS}
    b = {k: [] for k in report_agent._REDUCE_KEYS}
    a["facts"] = [_item("one", "said"), _item("two", "shown", 192.0)]
    b["facts"] = [_item("three", "both", 196.0)]
    b["speakers"] = [_item("presenter named on a lower third", "shown", 5.0)]
    out = report_agent.reduce_summaries({"job_type": "topic", "chunk_summaries": [a, b]})
    merged = out["chunk_summaries"][0]
    assert [i["modality"] for i in merged["facts"]] == ["said", "shown", "both"]
    assert merged["speakers"][0]["modality"] == "shown"
    assert json.loads(out["reduce_record"]["payload_json"])["facts"][1]["modality"] == "shown"


def test_reduce_unions_evidence_for_the_same_item():
    """Overlapping chunks can extract one item twice — once from the speech,
    once from the span. The union is 'both', not whichever came first."""
    said = {k: [] for k in report_agent._REDUCE_KEYS}
    shown = {k: [] for k in report_agent._REDUCE_KEYS}
    said["facts"] = [_item("version 0.13.2", "said")]
    shown["facts"] = [_item("version 0.13.2", "shown")]
    merged, notes = report_agent._merge_structurally([said, shown])
    assert len(merged["facts"]) == 1 and merged["facts"][0]["modality"] == "both"
    assert notes["reduce_exact_duplicates_collapsed"] == 1


def test_combine_modality_table():
    c = report_agent._combine_modality
    assert c("said", "said") == "said"
    assert c("said", "shown") == "both"
    assert c("shown", "both") == "both"
    assert c("unknown", "shown") == "shown"
    assert c(None, None) == "unknown"


# ---------- compose -----------------------------------------------------------

def _compose(items: list[dict]) -> list[str]:
    prompts: list[str] = []

    def capture(use_case, prompt, *, max_tokens, temperature, label=""):
        prompts.append(prompt)
        return "<h2>Key Facts</h2><p>x</p>"

    summary = {k: [] for k in report_agent._REDUCE_KEYS}
    summary["facts"] = items
    with patch.object(report_agent, "_invoke_with_retry", side_effect=capture):
        report_agent.compose_report({
            "job_type": "topic", "topic": "seaborn",
            "chunk_summaries": [summary], "statistics": {"video_count": 1},
        })
    return prompts


def test_compose_input_carries_the_tags_and_the_instruction():
    items = [
        _item("The presenter uses seaborn version 0.13.2.", "said"),
        _item("A ValueError traceback is visible.", "shown", 192.0),
        _item("A scatter plot is drawn.", "both", 196.0),
        _item("Unparsed batch text.", None),
    ]
    section = _compose(items)[0]
    assert '"content": "[SAID] The presenter uses seaborn version 0.13.2."' in section
    assert '"content": "[SHOWN] A ValueError traceback is visible."' in section
    assert '"content": "[SAID+SHOWN] A scatter plot is drawn."' in section
    assert '"content": "[UNLABELLED] Unparsed batch text."' in section
    assert section.count("EVIDENCE TAGS") == 1
    assert "Never print them in the report" in section
    # The label travels as the tag; the raw pipeline keys do not.
    assert '"modality"' not in section and '"modality_model"' not in section
    # Rendering copies — the consolidated items keep their labels untouched.
    assert items[0]["content"].startswith("The presenter")
    assert items[1]["modality"] == "shown"


def test_compose_without_shown_items_adds_no_tags():
    """A corpus with no visual evidence pays nothing for the feature."""
    section = _compose([_item("only speech here", "said")])[0]
    assert "[SAID]" not in section and "EVIDENCE TAGS" not in section
    assert '"modality"' not in section


def test_summary_prompt_is_unchanged_by_tags():
    """The summary reads written sections, not items; tags never reach it."""
    prompts = _compose([_item("x", "shown", 192.0)])
    summary = prompts[-1]
    assert "Executive Summary" in summary
    assert "EVIDENCE TAGS" not in summary


# ---------- prompt contracts ----------------------------------------------------

def test_map_prompt_binds_the_modality_rule():
    assert "{modality_rule}" in MAP_CHUNK_PROMPT
    assert "modality, and optionally original" in MAP_CHUNK_PROMPT
    assert "native digits included" in MODALITY_FIELD_RULE
    assert 'yields only "said" items' in MODALITY_FIELD_RULE


def test_compose_prompt_binds_the_tag_note():
    assert "{modality_labels}" in COMPOSE_SECTION_PROMPT
    for tag in ("[SAID]", "[SHOWN]", "[SAID+SHOWN]", "[UNLABELLED]"):
        assert tag in MODALITY_TAGS_NOTE


def test_converse_rule_is_in_the_contract_once():
    assert VISUAL_ANNOTATION_CONTRACT.count("CONVERSE:") == 1
    assert 'never "on screen"' in VISUAL_ANNOTATION_CONTRACT
    assert "০.১৩.২" in VISUAL_ANNOTATION_CONTRACT
    # The S-1.18.6 rule it complements is still there, once.
    assert VISUAL_ANNOTATION_CONTRACT.count("ATTRIBUTION BOUNDARY") == 1


# ---------- auditable (S-1.14.6) -------------------------------------------------

def test_labels_are_in_the_persisted_map_record_and_the_audit(db, capsys):
    """The point of sequencing after S-1.14.6: a run's labels can be checked
    after the fact, including where the pipeline overrode the model."""
    import importlib.util
    from pathlib import Path

    from app.models.job import Job
    from app.models.job_report_intermediate import STAGE_MAP, JobReportIntermediate
    from app.tasks.job_tasks import _persist_report_intermediates

    job = Job(job_type="topic", topic="seaborn", status="completed", num_videos=1)
    db.add(job)
    db.commit()
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=json.dumps(MODEL_OUTPUT, ensure_ascii=False))
    intermediates: dict = {}
    with patch.object(report_agent, "get_llm_for", return_value=llm), \
         patch.object(report_agent, "_invoke_with_retry", return_value="<h2>S</h2>"):
        report_agent.run_report_agent("topic", "seaborn", _chunks(with_frame=True),
                                      intermediates_out=intermediates)
    _persist_report_intermediates(db, job.id, intermediates)

    row = db.query(JobReportIntermediate).filter_by(job_id=job.id, stage=STAGE_MAP).one()
    facts = json.loads(row.payload_json)["facts"]
    assert [f["modality"] for f in facts] == ["said", "shown", "both"]
    # Frozen before compose: the record has the label, not the rendered tag.
    assert not any(f["content"].startswith("[") for f in facts)

    spec = importlib.util.spec_from_file_location(
        "audit_report_intermediates",
        Path(__file__).resolve().parents[2] / "scripts" / "audit_report_intermediates.py",
    )
    audit_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit_mod)
    audit_mod.audit(db, job.id[:8], None, show_batches=False)
    assert "map items by modality: " in capsys.readouterr().out
