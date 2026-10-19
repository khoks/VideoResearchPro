"""`temporal_service` — the era a source DISCUSSES (R3 / S-1.17.2).

Pure helpers are tested directly; the extraction call is exercised with a
fake LLM so the persist / reuse / fail-soft contract is pinned without a
network.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document
from app.services import temporal_service as ts


def _era(**over) -> dict:
    base = {"era_start": 2019, "era_end": 2021, "era_confidence": 0.8, "is_retrospective": True}
    base.update(over)
    return base


# ---------- parse_era_payload ---------------------------------------------

def test_parse_accepts_plain_json():
    out = ts.parse_era_payload(
        '{"era_start": 2019, "era_end": 2021, "era_confidence": 0.8, '
        '"is_retrospective": true, "era_label": "late 2010s"}'
    )
    assert out == _era(era_label="late 2010s")


def test_parse_tolerates_code_fences_and_prose():
    raw = 'Sure:\n```json\n{"era_start": 2020, "era_end": 2020, "era_confidence": 1, "is_retrospective": false}\n```'
    out = ts.parse_era_payload(raw)
    assert out["era_start"] == 2020 and out["era_end"] == 2020
    assert out["era_confidence"] == 1.0 and out["is_retrospective"] is False


def test_parse_corrects_swapped_bounds_and_clamps_confidence():
    out = ts.parse_era_payload(
        '{"era_start": 2021, "era_end": 2019, "era_confidence": 7, "is_retrospective": 1}'
    )
    assert (out["era_start"], out["era_end"]) == (2019, 2021)
    assert out["era_confidence"] == 1.0
    assert out["is_retrospective"] is True


def test_parse_lone_bound_becomes_point_era():
    out = ts.parse_era_payload(
        '{"era_start": null, "era_end": 1857, "era_confidence": 0.5, "is_retrospective": true}'
    )
    assert (out["era_start"], out["era_end"]) == (1857, 1857)


def test_parse_nulls_force_zero_confidence():
    """Undatable material: the model may still emit a confidence; it is meaningless."""
    out = ts.parse_era_payload(
        '{"era_start": null, "era_end": null, "era_confidence": 0.9, "is_retrospective": false}'
    )
    assert out["era_start"] is None and out["era_confidence"] == 0.0
    assert not ts.is_known(out)


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", '{"era_start": 2020}', '{"foo": 1}'])
def test_parse_rejects_malformed(raw):
    assert ts.parse_era_payload(raw) is None


def test_bce_years_are_negative_integers():
    out = ts.parse_era_payload(
        '{"era_start": -500, "era_end": -300, "era_confidence": 0.6, "is_retrospective": true}'
    )
    assert out["era_start"] == -500
    assert ts.era_span_text(out) == "500 BCE–300 BCE"


# ---------- sample_transcript ----------------------------------------------

def test_sample_returns_whole_text_when_short():
    assert ts.sample_transcript([{"text": "a b c"}, {"text": "d"}], window_tokens=100) == "a b c d"


def test_sample_takes_three_windows_when_long():
    words = [f"w{i}" for i in range(3000)]
    out = ts.sample_transcript(" ".join(words), window_tokens=50)
    assert out.count("[...]") == 2
    assert out.startswith("w0 ")
    assert out.rstrip().endswith("w2999")
    assert len(out.split()) < 400


def test_sample_empty_input():
    assert ts.sample_transcript([]) == ""
    assert ts.sample_transcript([{"text": "  "}]) == ""


# ---------- prompt / metadata rendering -------------------------------------

def test_era_for_prompt_variants():
    assert ts.era_for_prompt(None) == ""
    assert ts.era_for_prompt(_era()) == "discusses 2019–2021 (retrospective)"
    assert ts.era_for_prompt(_era(era_end=2019, is_retrospective=False)) == "discusses 2019"
    assert ts.era_for_prompt(_era(era_confidence=0.2, is_retrospective=False)) == (
        "discusses 2019–2021 (low confidence)"
    )
    assert ts.era_for_prompt(_era(era_confidence=0.0)) == ""


def test_era_metadata_omits_keys_when_unknown():
    """Chroma range filters must EXCLUDE undated chunks, so no sentinels."""
    assert ts.era_metadata(None) == {}
    assert ts.era_metadata(_era(era_start=None, era_end=None, era_confidence=0.0)) == {}
    md = ts.era_metadata(_era())
    assert md == {"era_start": 2019, "era_end": 2021, "era_confidence": 0.8, "is_retrospective": True}
    assert all(isinstance(v, (int, float, bool)) for v in md.values())


def test_era_from_chunk_metadata_round_trips():
    md = ts.era_metadata(_era())
    assert ts.era_for_prompt(ts.era_from_chunk_metadata(md)) == ts.era_for_prompt(_era())
    assert ts.era_from_chunk_metadata({"video_id": "v"}) is None


def test_summarize_and_describe_corpus_eras():
    summary = ts.summarize_eras([_era(), _era(era_start=2024, era_end=2026, is_retrospective=False), None])
    assert summary == {
        "era_known_count": 2,
        "discussed_era_start": 2019,
        "discussed_era_end": 2026,
        "retrospective_count": 1,
    }
    text = ts.describe_corpus_eras(summary)
    assert "2019–2026" in text and "2 source(s)" in text and "1 of them retrospective" in text
    assert ts.describe_corpus_eras(ts.summarize_eras([])) == ""


def test_published_display():
    assert ts.published_display(datetime(2025, 3, 12, 10, tzinfo=timezone.utc)) == "2025-03-12"
    assert ts.published_display("2025-03-12T10:00:00Z") == "2025-03-12"
    assert ts.published_display(None) == ""


# ---------- extraction + persistence ---------------------------------------

def _fake_llm(payload: str) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=payload)
    return llm


def test_extract_builds_prompt_and_stamps_provenance():
    llm = _fake_llm(json.dumps(_era(era_label="x")))
    era = ts.extract_discussed_era(
        "Title", "desc", datetime(2026, 1, 1), [{"text": "we look back at 2019 to 2021"}], llm=llm
    )
    prompt = llm.invoke.call_args.args[0][0].content
    assert 'Source title: "Title"' in prompt
    assert "Published: 2026-01-01" in prompt
    assert "we look back at 2019" in prompt
    assert era["era_start"] == 2019
    assert era["extracted_at"] and "model" in era


def test_extract_returns_none_on_llm_error_or_bad_json():
    boom = MagicMock()
    boom.invoke.side_effect = RuntimeError("down")
    assert ts.extract_discussed_era("T", None, None, "text", llm=boom) is None
    assert ts.extract_discussed_era("T", None, None, "text", llm=_fake_llm("nope")) is None


def test_extract_skips_empty_transcript_without_calling():
    llm = _fake_llm("{}")
    assert ts.extract_discussed_era("T", None, None, [], llm=llm) is None
    llm.invoke.assert_not_called()


def test_ensure_persists_once_and_reuses(db):
    doc = Document(video_id="v1", title="T", url="u", published_at=datetime(2026, 1, 1))
    db.add(doc)
    db.commit()

    with patch.object(ts, "extract_discussed_era", return_value=_era()) as ext:
        first = ts.ensure_discussed_era(db, doc, [{"text": "x"}])
        second = ts.ensure_discussed_era(db, doc, [{"text": "x"}])

    assert first["era_start"] == 2019 and second["era_start"] == 2019
    ext.assert_called_once()
    db.refresh(doc)
    assert json.loads(doc.discussed_era_json)["era_end"] == 2021


def test_ensure_failure_is_not_persisted(db):
    """A transient outage must be retried by the next job, not frozen as unknown."""
    doc = Document(video_id="v2", title="T", url="u")
    db.add(doc)
    db.commit()
    with patch.object(ts, "extract_discussed_era", return_value=None):
        assert ts.ensure_discussed_era(db, doc, "text") is None
    db.refresh(doc)
    assert doc.discussed_era_json is None


def test_ensure_respects_kill_switch(db):
    doc = Document(video_id="v3", title="T", url="u")
    db.add(doc)
    db.commit()
    with patch.object(ts.settings, "TEMPORAL_SCOPE_ENABLED", False), \
         patch.object(ts, "extract_discussed_era") as ext:
        assert ts.ensure_discussed_era(db, doc, "text") is None
    ext.assert_not_called()


def test_ensure_malformed_existing_value_is_unknown_without_a_call():
    doc = SimpleNamespace(discussed_era_json="{broken", title="T", description=None, published_at=None)
    with patch.object(ts, "extract_discussed_era") as ext:
        assert ts.ensure_discussed_era(None, doc, "text") is None
    ext.assert_not_called()


def test_known_eras_for_reads_only_known(db):
    db.add(Document(video_id="k1", title="a", url="u", discussed_era_json=json.dumps(_era())))
    db.add(Document(video_id="k2", title="b", url="u", discussed_era_json=json.dumps(
        _era(era_start=None, era_end=None, era_confidence=0.0))))
    db.add(Document(video_id="k3", title="c", url="u"))
    db.commit()
    out = ts.known_eras_for(db, ["k1", "k2", "k3", "missing"])
    assert set(out) == {"k1"}
    assert ts.known_eras_for(db, []) == {}
