"""R1 visual annotations — the guarantees that must not silently break.

The requirement is not "attach descriptions to transcripts". It is attach
them **clearly annotated, so downstream prompts read them as visual aid and
never as spoken words**. Every test here defends that second half, because
the first half failing is obvious and the second half failing is not: a
shredded annotation still produces a plausible report, made of sentences
nobody said.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.agents.prompts.shared import VISUAL_ANNOTATION_CONTRACT
from app.services.visual_service import (
    annotate_segments,
    format_annotation,
    format_timestamp,
    strip_annotations,
)
from app.utils.chunking import chunk_transcript


@dataclass
class FakeFrame:
    timestamp_seconds: float
    description: str
    informative: bool = True
    status: str = "described"


def _speech(text: str, start: float, duration: float = 5.0) -> dict:
    return {"text": text, "start": start, "duration": duration}


# ---------------------------------------------------------------------------
# Annotation format
# ---------------------------------------------------------------------------
def test_format_annotation_shape():
    out = format_annotation(132, "a bar chart of revenue by quarter")
    assert out == "[VISUAL @ 2:12 — a bar chart of revenue by quarter]"


def test_format_timestamp_crosses_the_hour():
    assert format_timestamp(59) == "0:59"
    assert format_timestamp(3600) == "1:00:00"
    assert format_timestamp(3725) == "1:02:05"


def test_closing_bracket_inside_a_description_cannot_end_the_annotation_early():
    """A `]` in the description would make everything after it read as speech.

    This is the highest-consequence formatting bug available here: a model
    reading `[VISUAL @ 0:10 — code: arr[0]] and then he said...` sees the
    annotation close at `arr[0]` and treats the rest as spoken words.
    """
    out = format_annotation(10, "code showing arr[0] being indexed")
    assert out.count("]") == 1
    assert out.endswith("]")


def test_description_whitespace_is_normalised():
    assert format_annotation(0, "  a  chart\n\nwith gaps ") == "[VISUAL @ 0:00 — a chart with gaps]"


# ---------------------------------------------------------------------------
# Merge behaviour
# ---------------------------------------------------------------------------
def test_annotations_are_interleaved_in_timestamp_order():
    segments = [_speech("first", 0), _speech("second", 60), _speech("third", 120)]
    frames = [FakeFrame(65, "a chart"), FakeFrame(5, "a slide")]

    merged = annotate_segments(segments, frames)

    assert [s["start"] for s in merged] == [0, 5, 60, 65, 120]
    assert merged[1]["text"].startswith("[VISUAL @ 0:05")
    assert merged[3]["text"].startswith("[VISUAL @ 1:05")


def test_annotation_follows_speech_at_the_same_timestamp():
    """"As you can see here" then the description of "here" — not the reverse."""
    merged = annotate_segments([_speech("as you can see here", 30)], [FakeFrame(30, "a chart")])
    assert merged[0]["text"] == "as you can see here"
    assert merged[1]["text"].startswith("[VISUAL")


def test_uninformative_and_failed_frames_are_not_merged():
    frames = [
        FakeFrame(10, "a man speaking to camera", informative=False),
        FakeFrame(20, "", status="failed"),
        FakeFrame(30, "   \n  "),
        FakeFrame(40, "a chart of revenue"),
    ]
    merged = annotate_segments([_speech("hello", 0)], frames)
    annotations = [s for s in merged if "[VISUAL" in s["text"]]
    assert len(annotations) == 1
    assert "revenue" in annotations[0]["text"]


def test_annotate_segments_does_not_mutate_its_input():
    """The transcript comes from the globally-shared cache — mutating it would
    rewrite every other job's and tenant's source text."""
    segments = [_speech("hello", 0)]
    original = [dict(s) for s in segments]
    annotate_segments(segments, [FakeFrame(5, "a chart")])
    assert segments == original
    assert len(segments) == 1


def test_no_frames_returns_the_transcript_unchanged():
    segments = [_speech("hello", 0), _speech("world", 10)]
    assert annotate_segments(segments, []) == segments
    assert annotate_segments(segments, None) == segments


# ---------------------------------------------------------------------------
# Survival through chunking — the two known blockers
# ---------------------------------------------------------------------------
def test_annotation_survives_chunking_intact():
    """Blocker A: `_expand_segments_to_sentences` splits multi-sentence text
    and interpolates fake timestamps. A multi-sentence description would be
    torn into fragments, leaving the opening marker on one and the closing
    bracket on another — with the middle sentences reading as speech."""
    description = (
        "A bar chart of quarterly revenue. The y-axis is labelled USD millions. "
        "Q4 reaches 5.8 while Q1 sits at 2.1."
    )
    segments = annotate_segments(
        [_speech("as you can see here", 30)], [FakeFrame(30, description)]
    )
    chunks = chunk_transcript(segments, chunk_size=256, chunk_overlap=32,
                              video_metadata={"video_id": "v1"})

    all_text = " ".join(c["text"] for c in chunks)
    expected = format_annotation(30, description)
    assert expected in all_text, "annotation was split or reworded by chunking"
    # Exactly one opening marker and one closing bracket for it.
    assert all_text.count("[VISUAL") == 1


def test_visual_metadata_survives_a_chunk_dominated_by_speech():
    """Blocker B: the dominant-segment heuristic promotes ONE segment's
    metadata. A 12-token annotation next to 240 tokens of speech always loses
    that vote, so visual presence is aggregated separately instead."""
    long_speech = "word " * 240
    segments = annotate_segments(
        [_speech(long_speech, 0, duration=60)], [FakeFrame(30, "a chart of revenue")]
    )
    chunks = chunk_transcript(segments, chunk_size=4096, chunk_overlap=0,
                              video_metadata={"video_id": "v1"})

    assert len(chunks) == 1
    md = chunks[0]["metadata"]
    assert md["visual_frame_count"] == 1
    assert md["visual_timestamps"] == "30"


def test_annotation_does_not_steal_reply_attribution_from_speech():
    """The dominant vote decides whose REPLY a chunk cites. An annotation
    belongs to no reply — a long description outvoting a short comment would
    blank the citation target."""
    segments = [
        {"text": "short comment", "start": 0, "duration": 5,
         "extra": {"kind": "comment", "comment_id": "abc", "author": "alice"}},
    ]
    long_desc = "A detailed chart. " * 40
    segments = annotate_segments(segments, [FakeFrame(1, long_desc)])
    chunks = chunk_transcript(segments, chunk_size=4096, chunk_overlap=0,
                              video_metadata={"video_id": "v1"})

    md = chunks[0]["metadata"]
    assert md["comment_id"] == "abc"
    assert md["segment_author"] == "alice"
    assert md["segment_kind"] == "comment"
    assert md["visual_frame_count"] == 1


def test_chunks_without_visuals_report_zero_not_missing():
    chunks = chunk_transcript([_speech("hello world", 0)], video_metadata={"video_id": "v1"})
    md = chunks[0]["metadata"]
    assert md["visual_frame_count"] == 0
    assert md["visual_timestamps"] == ""


def test_multiple_annotations_in_one_chunk_are_all_counted():
    segments = annotate_segments(
        [_speech("talking", 0, duration=120)],
        [FakeFrame(10, "a slide"), FakeFrame(40, "a chart"), FakeFrame(70, "a diagram")],
    )
    chunks = chunk_transcript(segments, chunk_size=4096, chunk_overlap=0,
                              video_metadata={"video_id": "v1"})
    md = chunks[0]["metadata"]
    assert md["visual_frame_count"] == 3
    assert md["visual_timestamps"] == "10,40,70"


# ---------------------------------------------------------------------------
# Stripping
# ---------------------------------------------------------------------------
def test_strip_annotations_recovers_the_spoken_text():
    """Speech-only surfaces (dataset exports, word counts, and especially the
    R5 language profiler) must not measure our own English annotations."""
    text = "as you can see here [VISUAL @ 0:30 — a chart of revenue] and that is the trend"
    assert strip_annotations(text) == "as you can see here and that is the trend"


def test_strip_annotations_is_a_noop_without_markers():
    assert strip_annotations("plain speech") == "plain speech"


def test_strip_annotations_keeps_text_after_an_unterminated_marker():
    """Better to leave a malformed marker visible than to swallow real speech."""
    out = strip_annotations("hello [VISUAL @ 0:30 — broken and then real speech")
    assert "real speech" in out


# ---------------------------------------------------------------------------
# The reader contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("required", [
    "NOT spoken words",
    "Never quote them as",
    "on screen at",
    "prefer the words",
])
def test_reader_contract_states_the_non_negotiables(required):
    """The annotation format is only half the requirement; the other half is
    that models are told how to read it."""
    assert required in VISUAL_ANNOTATION_CONTRACT


def test_marker_in_the_contract_matches_the_marker_we_emit():
    """If these drift, every prompt teaches models to look for a marker that
    is no longer produced — and the annotations silently become speech."""
    emitted = format_annotation(90, "a chart")
    assert emitted.startswith("[VISUAL @ ")
    assert "`[VISUAL @ mm:ss — <description of what is on screen>]`" in VISUAL_ANNOTATION_CONTRACT
