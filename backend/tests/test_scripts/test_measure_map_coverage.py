"""measure_map_coverage.py — the coverage figures the batch-cap decision rests on."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import measure_map_coverage as mmc  # noqa: E402


def test_source_key_reads_the_video_id_from_any_url_spelling():
    assert mmc.source_key({"video_url": "https://www.youtube.com/watch?v=50SGBO3Psqk&t=12"}) == "50SGBO3Psqk"
    assert mmc.source_key({"url": "https://youtu.be/0sk72TEs3zc"}) == "0sk72TEs3zc"
    assert mmc.source_key({"video_id": "doc-1"}) == "doc-1"


def test_items_are_counted_per_source_across_categories_and_batches():
    url = "https://www.youtube.com/watch?v={}"
    summaries = [
        {"facts": [{"video_url": url.format("aaaaaaaaaaa")}, {"video_url": url.format("bbbbbbbbbbb")}],
         "speakers": [{"video_url": url.format("aaaaaaaaaaa")}], "note": "not a list"},
        {"raw": "unparsed batch"},
        None,
    ]
    assert mmc.items_by_source(summaries) == Counter({"aaaaaaaaaaa": 2, "bbbbbbbbbbb": 1})


def test_coverage_flags_an_empty_source_and_ignores_tiny_ones():
    chunks = Counter({"big": 40, "late": 20, "tiny": 2})
    items = Counter({"big": 20})
    c = mmc.coverage(chunks, items)
    assert c["zero_item_sources"] == ["late"]          # "tiny" is below the eligibility floor
    assert c["density_min"] == 0.0
    assert c["floor_ratio"] == 0.0


def test_floor_ratio_compares_the_thinnest_source_to_the_median():
    chunks = Counter({"a": 10, "b": 10, "c": 10})
    items = Counter({"a": 10, "b": 5, "c": 2})
    c = mmc.coverage(chunks, items)
    assert c["zero_item_sources"] == []
    assert (c["density_min"], c["density_median"], c["floor_ratio"]) == (0.2, 0.5, 0.4)


def test_items_citing_no_known_source_are_counted_not_credited():
    c = mmc.coverage(Counter({"a": 10}), Counter({"a": 3, "?": 2}))
    assert c["unattributed_items"] == 2
    assert c["per_source"]["a"]["items"] == 3


def test_spans_are_indexed_per_source_in_seconds():
    chunks = [
        {"text": "speech [VISUAL @ 2:54 — 0.13.2 printed] more", "metadata": {"video_url": "https://youtu.be/simplilearn"}},
        {"text": "[VISUAL @ 1:02:03 — a chart]", "metadata": {"video_id": "long"}},
    ]
    assert mmc.span_index(chunks) == {"simplilearn": [174.0], "long": [3723.0]}


def test_a_shown_label_without_an_own_source_span_nearby_is_cross_source():
    # The run-6 case: CodeWithMunnaX says 0.13.2 at 2:57; the only span showing
    # it is Simplilearn's at 2:54. CodeWithMunnaX's own nearest span is 2:38.
    spans = {"munnaxMunna": [158.0, 267.0], "simplilearn": [174.0]}
    item = {"modality": "both", "video_url": "https://youtu.be/munnaxMunna", "timestamp_seconds": 177,
            "timestamp_display": "2:57–3:22"}
    assert mmc.item_window(item) == (117.0, 262.0)
    assert mmc.cross_source_labels([{"facts": [item]}], spans) == 0      # 2:38 is inside the window
    far = dict(item, timestamp_seconds=600, timestamp_display="10:00")
    assert mmc.cross_source_labels([{"facts": [far]}], spans) == 1
    said = dict(far, modality="said")
    assert mmc.cross_source_labels([{"facts": [said]}], spans) == 0
