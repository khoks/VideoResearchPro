"""voice_match_harness.py: the parts that turn verdicts into the S-3.3.4 result.

The model calls are not exercised. What must never be wrong is the rule
pre-registered in docs/notes/2026-10-19-voice-match-preregistration.md:
the unblinding (a verdict for "A" is a win for whichever condition was shown
as A), abstentions left out of the shares but counted against the 50% cap,
and each threshold applied as written.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from voice_match_harness import _exemplars, _verdict, score, user_score  # noqa: E402

PERSONAS = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "echo_voice" / "personas.json").read_text(encoding="utf-8")
)["personas"]
J1, J2 = "anthropic:claude-sonnet-5", "google:gemini-3.6-flash"


def _item(writer, v_is, voice, quality=("TIE", "TIE"), s_v=0.6, s_n=0.5):
    return {
        "writer": writer,
        "v_is": v_is,
        "voice_verdicts": {J1: voice[0], J2: voice[1]},
        "quality_verdicts": {J1: quality[0], J2: quality[1]},
        "s_v": s_v,
        "s_n": s_n,
        "v_attributed_to": writer,
        "n_attributed_to": "bharat",
    }


def test_unblinding_follows_the_coin_flip():
    # V shown as B and both judges say B: two V wins. V shown as A, judges say B: two N wins.
    r = score([_item("asha", "B", ("B", "B")), _item("asha", "A", ("B", "B"))])
    assert r["voice"]["pooled_v_share"] == 0.5
    assert r["voice"]["per_judge"][J1] == {"v_share": 0.5, "decided": 2}


def test_abstentions_leave_the_shares_but_count_against_the_cap():
    items = [_item("asha", "A", ("A", "UNSURE")), _item("bharat", "A", ("UNSURE", "UNSURE"))]
    r = score(items)
    assert r["voice"]["pooled_v_share"] == 1.0
    assert r["voice"]["abstain_share"] == 0.75
    assert r["rules"]["voice_3_abstain_le_0.50"] is False
    assert r["voice"]["per_writer"]["bharat"]["v_share"] is None
    assert r["rules"]["voice_4_no_writer_below_half"] is False, "a writer with no decided verdict cannot pass"


def _passing(n_writers=("asha", "bharat", "chetan")):
    items = []
    for w in n_writers:
        # 6 prompts per writer: V wins 5 of 6 for each judge.
        for k in range(6):
            v_is = "A" if k % 2 else "B"
            win = v_is
            lose = "B" if v_is == "A" else "A"
            items.append(_item(w, v_is, (win if k else lose, win if k else lose), quality=(win, "TIE")))
    return items


def test_a_clear_win_passes_every_rule():
    r = score(_passing())
    assert r["voice"]["pooled_v_share"] == round(15 / 18, 3)
    assert r["voice_pass"] and r["quality_pass"] and r["tier1_pass"] and r["gate_for_s34_design"]


def test_seventy_percent_is_the_line():
    def run(wins_out_of_10):
        items = []
        for k in range(10):
            v_is = "A"
            verdict = "A" if k < wins_out_of_10 else "B"
            items.append(_item("asha", v_is, (verdict, verdict)))
        return score(items)

    assert run(7)["rules"]["voice_1_pooled_v_share_ge_0.70"] is True
    assert run(6)["rules"]["voice_1_pooled_v_share_ge_0.70"] is False


def test_one_judge_below_sixty_fails_even_when_the_pool_passes():
    items = [_item("asha", "A", ("A", "A" if k < 5 else "B")) for k in range(10)]
    r = score(items)
    assert r["voice"]["pooled_v_share"] == 0.75
    assert r["rules"]["voice_2_each_judge_ge_0.60"] is False


def test_quality_guard_counts_ties_for_the_voice_draft():
    items = [_item("asha", "A", ("A", "A"), quality=q) for q in (("TIE", "B"), ("B", "B"), ("A", "B"), ("B", "B"), ("B", "B"))]
    r = score(items)
    assert r["quality"]["counts"] == {"v": 1, "n": 8, "tie": 1, "unparsed": 0}
    assert r["quality"]["v_or_tie_share"] == 0.2 and not r["quality_pass"]
    assert r["gate_for_s34_design"] is False, "a voice win with worse writing does not open S-3.4"


def test_tier_one_needs_twelve_of_eighteen():
    items = [_item("asha", "A", ("A", "A"), s_v=0.6 if k < 12 else 0.4, s_n=0.5) for k in range(18)]
    assert score(items)["tier1_pass"] is True
    items[0]["s_v"] = 0.4
    assert score(items)["tier1_pass"] is False


def test_verdict_parsing_is_strict_about_unknown_answers():
    assert _verdict("A", ("A", "B", "UNSURE")) == "A"
    assert _verdict("**B**", ("A", "B", "UNSURE")) == "B"
    assert _verdict("unsure", ("A", "B", "UNSURE")) == "UNSURE"
    assert _verdict("Neither, honestly.", ("A", "B", "UNSURE")) == "UNPARSED"
    assert _verdict("tie", ("A", "B", "TIE")) == "TIE"


def test_exemplars_span_the_writers_range_not_one_topic():
    notes = PERSONAS["bharat"]["notes"]
    picked = _exemplars(notes)
    assert len(picked) == 5 and len(set(picked)) == 5
    from app.services import echo_stylometry as stylo

    lengths = sorted(stylo.profile(t).mean_sentence_words for t in notes)
    got = sorted(stylo.profile(t).mean_sentence_words for t in picked)
    assert got[0] == lengths[0] and got[-1] == lengths[-1]


def test_user_score_applies_the_tier_three_rule(tmp_path):
    key = [{"pair": f"p{i:02d}", "own_is": "A"} for i in range(20)]
    (tmp_path / "key.json").write_text(json.dumps(key))
    answers = {f"p{i:02d}": ("A" if i < 16 else "B") for i in range(20)}
    (tmp_path / "answers.json").write_text(json.dumps(answers))
    assert user_score(tmp_path / "key.json", tmp_path / "answers.json") == {"pairs": 20, "picked_own_share": 0.8, "pass": True}
    answers["p16"] = "A"
    (tmp_path / "answers.json").write_text(json.dumps(answers))
    assert user_score(tmp_path / "key.json", tmp_path / "answers.json")["pass"] is False
