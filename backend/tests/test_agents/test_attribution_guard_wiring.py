"""S-1.18.9 at its production callers: `map_chunks` and `compose_report`.

The guard is worth nothing unwired (R4's Q&A half shipped as dead code, S-1.15.2),
so these drive the real report stages with stub models and assert on what
leaves them. The input is R1 run 8's confirmed error: a sentence crediting
Data Analytics Lab with seven weekday totals that exist only in the
`[VISUAL @ 18:24]` span. Turning the guard off reproduces the error exactly,
which is what makes the first test a mutation test: remove the guard from
`compose_report` and it fails.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from app.agents import report_agent
from app.agents.prompts.shared import MODALITY_TAGS_NOTE
from app.services.visual_service import annotate_segments
from app.utils.chunking import chunk_transcript

URL = "https://www.youtube.com/watch?v=OEWAgzYv2mE"
TITLE = "Seaborn Python Tutorial: How to Analyze Data"
TOTALS = ("Mon 1 17363.10; Tue 2 18158.38; Wed 3 15750.46; Thu 4 16091.40; "
          "Fri 5 16802.66; Sat 6 14733.52; Sun 7 13336.06")


@dataclass
class _Frame:
    timestamp_seconds: float
    description: str
    informative: bool = True
    status: str = "described"


def _chunks(with_frame: bool = True) -> list[dict]:
    segments = [
        {"text": "Now let's look at our sales by weekday.", "start": 1039.0, "duration": 10.0},
        {"text": "So you'll see here we have our weekday, we have our sort order, and we have the total "
                 "amount spent on that weekday across all of the data.", "start": 1050.0, "duration": 14.0},
        {"text": "And you can see Tuesday is generally our best sales day.", "start": 1112.0, "duration": 8.0},
    ]
    if with_frame:
        segments = annotate_segments(segments, [_Frame(1104.0, f"A notebook cell shows `day_totals`: {TOTALS}.")])
    return chunk_transcript(segments, chunk_size=256, chunk_overlap=32, video_metadata={
        "video_id": "OEWAgzYv2mE", "title": TITLE, "channel_name": "Data Analytics Lab", "url": URL,
    })


def _item(content: str, modality: str, **extra) -> dict:
    item = {"content": content, "video_title": TITLE, "channel_name": "Data Analytics Lab",
            "timestamp_display": "17:19–18:24", "timestamp_seconds": 1039, "video_url": f"{URL}&t=1039",
            "speaker": "Presenter", "modality": modality}
    item.update(extra)
    return item


WEEKDAY_ITEM = ("The weekday totals in the heat-map example are Monday 17,363.10; Tuesday 18,158.38; "
                "Wednesday 15,750.46; Thursday 16,091.40; Friday 16,802.66; Saturday 14,733.52; and "
                "Sunday 13,336.06.")
CREDITED = ("Data Analytics Lab reads the coffee data to a full story, with Tuesday as the strongest sales "
            "day (Monday 17,363.10; Tuesday 18,158.38; Wednesday 15,750.46; Thursday 16,091.40; Friday "
            "16,802.66; Saturday 14,733.52; Sunday 13,336.06)")
SECTION = (f'<h2>Key Facts</h2><p>{CREDITED} (<a href="{URL}&t=1039" target="_blank">17:19</a>).</p>')
SUMMARY = f"<h2>Executive Summary</h2><p>The exceptions are instructive: {CREDITED}.</p>"


def _compose(items: list[dict], chunks: list[dict], section: str = SECTION, summary: str = SUMMARY):
    prompts: list[str] = []
    outputs = iter([section, summary])

    def fake_invoke(use_case, prompt, **kw):
        prompts.append(prompt)
        return next(outputs, "")

    with patch.object(report_agent, "_invoke_with_retry", side_effect=fake_invoke):
        out = report_agent.compose_report({
            "job_type": "topic", "topic": "seaborn", "statistics": {"video_count": 1},
            "chunk_summaries": [{"facts": items}], "transcript_chunks": chunks,
        })
    return out, prompts


# ---------- compose ------------------------------------------------------------

def test_compose_marks_run8_in_the_sections_and_the_summary_and_discloses_it():
    out, prompts = _compose([_item(WEEKDAY_ITEM, "shown")], _chunks())
    html = out["final_html"]
    marked = ("sales day (on screen at 18:24: Monday 17,363.10; Tuesday 18,158.38; Wednesday "
              "15,750.46; Thursday 16,091.40; Friday 16,802.66; Saturday 14,733.52; Sunday 13,336.06)")
    assert html.count(marked) == 2                      # the section and the executive summary
    # The summary was written from the guarded section, not from the error.
    assert "on screen at 18:24: Monday" in prompts[1] and "not spoken" not in html
    notes = out["processing_notes"]
    assert notes["report_attribution_marked"] == 2
    assert notes["report_attribution_speech_marked"] == 0 and notes["report_screen_claims_removed"] == 0
    assert len(notes["report_attribution_rewrites"]) == 2
    assert ("2 detail(s) in sentences crediting a speaker appear in a description of the screen near the "
            "cited moment but could not be matched to the speech there") in html
    assert "only on screen" not in html and notes["report_attribution_unchecked_sources"] == 0
    assert "not checked" not in html


def _bengali_chunks() -> list[dict]:
    segments = annotate_segments(
        [{"text": "এখানে অনেক ডেটাসেট আছে, আমরা এগুলো ব্যবহার করতে পারি।", "start": 596.0, "duration": 10.0}],
        [_Frame(613.0, "Output of sns.get_dataset_names(): ['dowjones', 'fmri', 'geyser'].")])
    return chunk_transcript(segments, chunk_size=256, chunk_overlap=32, video_metadata={
        "video_id": "5AuuOZ4vuxI", "title": "01. Seaborn in Python", "channel_name": "CodeWithMunnaX",
        "url": "https://www.youtube.com/watch?v=5AuuOZ4vuxI",
    })


def test_compose_discloses_the_sources_it_cannot_read():
    """T-1.18.9.11: a Bengali source with frames is left as written, and the note says so."""
    out, _ = _compose([_item(WEEKDAY_ITEM, "shown")], _chunks() + _bengali_chunks())
    html = out["final_html"]
    assert out["processing_notes"]["report_attribution_unchecked_sources"] == 1
    assert ("on-screen details credited to a speaker were not checked in 1 source(s) whose speech is not "
            "English in Latin script, which the check cannot read") in html


def test_without_the_guard_the_same_output_keeps_run8s_error():
    """The control for the test above: the stub composer really does produce the error."""
    with patch.object(report_agent.settings, "REPORT_ATTRIBUTION_GUARD_ENABLED", False):
        out, _ = _compose([_item(WEEKDAY_ITEM, "shown")], _chunks())
    html = out["final_html"]
    assert "sales day (Monday 17,363.10;" in html and "on screen at 18:24" not in html
    assert out["processing_notes"]["report_attribution_marked"] == 0


def test_compose_names_screen_only_details_in_the_tag():
    item = _item("Tuesday is generally the best sales day; Monday's total is 17,363.10.", "both",
                 screen_only=["17,363.10"])
    _, prompts = _compose([item], _chunks(), section="<h2>Key Facts</h2><p>Plain.</p>")
    assert "[SAID+SHOWN; shown on screen: 17,363.10] Tuesday is generally the best sales day" in prompts[0]
    assert "screen_only" not in prompts[0]
    assert MODALITY_TAGS_NOTE in prompts[0] and "[SAID+SHOWN; shown on screen: X | Y]" in MODALITY_TAGS_NOTE


def test_a_corpus_without_visual_spans_is_composed_exactly_as_before():
    plain = _chunks(with_frame=False)
    out, _ = _compose([_item(WEEKDAY_ITEM, "said")], plain)
    assert "sales day (Monday 17,363.10;" in out["final_html"]
    assert out["processing_notes"]["report_attribution_rewrites"] == []


# ---------- map ----------------------------------------------------------------

def _map(chunks: list[dict], items: list[dict]):
    payload = {"facts": items, "comments": [], "conclusions": [], "references": [], "speakers": []}
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        return report_agent.map_chunks({"job_type": "topic", "topic": "seaborn", "transcript_chunks": chunks})


def test_map_lists_the_run8_weekday_totals_and_records_them():
    out = _map(_chunks(), [_item(WEEKDAY_ITEM, "both")])
    fact = out["chunk_summaries"][0]["facts"][0]
    totals = ["17,363.10", "18,158.38", "15,750.46", "16,091.40", "16,802.66", "14,733.52", "13,336.06"]
    # Never relabelled `shown`: that would say the totals went unsaid (T-1.18.9.11).
    assert fact["modality"] == "both" and fact["screen_only"] == totals
    assert out["processing_notes"]["map_attribution_guard"] == {"listed": 1}
    # The S-1.14.6 audit record keeps what the guard listed.
    record = json.loads(out["map_batch_records"][0]["payload_json"])
    assert record["facts"][0]["screen_only"] == totals


def test_map_leaves_a_corpus_without_spans_alone():
    out = _map(_chunks(with_frame=False), [_item(WEEKDAY_ITEM, "both")])
    assert out["chunk_summaries"][0]["facts"][0]["modality"] == "said"   # forced by S-1.18.8
    assert out["processing_notes"]["map_attribution_guard"] == {}


def test_a_guard_failure_never_costs_content():
    """A bug in the guard must not fail a map batch (it would be bisected and dropped) or a report."""
    with patch.object(report_agent.attribution_guard, "label_items", side_effect=RuntimeError("boom")):
        out = _map(_chunks(), [_item(WEEKDAY_ITEM, "both")])
    assert out["chunk_summaries"][0]["facts"][0]["modality"] == "both"      # the mapped label stands
    assert out["processing_notes"]["map_attribution_guard"] == {"failed": 1}
    assert out["processing_notes"]["map_batches_failed"] == 0

    with patch.object(report_agent.attribution_guard, "guard_report", side_effect=RuntimeError("boom")):
        composed, _ = _compose([_item(WEEKDAY_ITEM, "shown")], _chunks())
    assert "sales day (Monday 17,363.10;" in composed["final_html"]          # shown as written
    assert composed["processing_notes"]["report_attribution_guard_failures"] == 2
    assert "failed on 2 passage(s), which are shown as written" in composed["final_html"]


def test_the_guard_switch_turns_both_stages_off():
    with patch.object(report_agent.settings, "REPORT_ATTRIBUTION_GUARD_ENABLED", False):
        out = _map(_chunks(), [_item(WEEKDAY_ITEM, "both")])
    assert out["chunk_summaries"][0]["facts"][0]["modality"] == "both"
    assert out["processing_notes"]["map_attribution_guard"] == {}
