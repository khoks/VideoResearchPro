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
    assert user_score(tmp_path / "key.json", tmp_path / "answers.json") == {"pairs": 20, "picked_own_share": 0.8, "pass": True, "picked_own": 16}
    answers["p16"] = "A"
    (tmp_path / "answers.json").write_text(json.dumps(answers))
    assert user_score(tmp_path / "key.json", tmp_path / "answers.json")["pass"] is False


# ---------------------------------------------------------------------------
# T-3.4.1.8: the procedure moved into echo_voice_test_service; the script
# calls it. Same score, same output, same gate row as before the move.

USER_TEST = Path(__file__).resolve().parents[1] / "fixtures" / "echo_voice" / "user_test"
#: What the script printed for the fixture before the move (master at
#: dc11f41, run 2026-11-04): the user picked their own text in 15 of 20.
SCRIPT_OUTPUT = '{\n  "pairs": 20,\n  "picked_own_share": 0.75,\n  "pass": true\n}\nrecorded: passed (20 pairs, own text picked in 75%)\n'


def test_the_script_scores_the_fixture_as_before(tmp_path):
    """``user-score --record`` end to end, as the operator runs it: the same
    printed score and the same gate row, written to the --record database
    and nowhere else."""
    import os
    import subprocess

    from sqlalchemy import create_engine, text

    from app.database import Base

    live = tmp_path / "live.db"
    engine = create_engine(f"sqlite:///{live.as_posix()}")
    Base.metadata.create_all(engine)
    script = Path(__file__).resolve().parents[2] / "scripts" / "voice_match_harness.py"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{(tmp_path / 'elsewhere.db').as_posix()}", "PYTHONIOENCODING": "utf-8"}
    run = subprocess.run(
        [sys.executable, str(script), "user-score", "--key", str(USER_TEST / "key.json"),
         "--answers", str(USER_TEST / "answers.json"), "--record", str(live), "--tenant", "tenant-1"],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.replace("\r\n", "\n") == SCRIPT_OUTPUT
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT tenant_id, status, pairs, picked_own_share, rule_version FROM echo_voice_gates")).all()
    engine.dispose()
    assert [tuple(r) for r in rows] == [("tenant-1", "passed", 20, 0.75, "2026-10-19")]
    assert not (tmp_path / "elsewhere.db").exists(), "the gate went to the --record database only"


#: Runs ``user-pairs`` in its own process, as it binds the app to the copy of
#: the database at import. The model is replaced: no provider is called.
PAIRS_DRIVER = r"""
import os, pathlib, sys

db_path, tenant, small_tenant, out, key, scripts, module = sys.argv[1:8]
os.environ.update({
    "DATABASE_URL": "sqlite:///" + pathlib.Path(db_path).as_posix(),
    "CHROMA_PERSIST_DIR": str(pathlib.Path(out).parent / "chroma"),
    "ECHO_PERSONAL_INDEX_ENABLED": "False",
    "NOTES_INDEX_ENABLED": "False",
})
sys.path.insert(0, scripts)
harness = __import__(module)
from app.services import echo_signal_extraction as ex


def ask(client, prompt):
    if prompt.startswith("In at most twelve words"):
        return "topic " + prompt.split("Note:\n", 1)[1][:24], 40, 6
    return "draft for " + prompt.split("Situation:\n", 1)[1].split("\n", 1)[0], 900, 60


harness._client = lambda cfg, max_tokens: object()
harness._ask = ask
ex._default_llm = lambda tenant_id, db: ((lambda prompt: ('{"signals": []}', 1, 1)), "fake")
try:
    harness.user_pairs(pathlib.Path(db_path), small_tenant, pathlib.Path(out), pathlib.Path(key))
except SystemExit as e:
    print("refused:", e)
harness.user_pairs(pathlib.Path(db_path), tenant, pathlib.Path(out), pathlib.Path(key))
"""


def test_user_pairs_still_builds_the_pairs_on_a_copy(tmp_path):
    """The script end to end with the model replaced: its fixed seed picks the
    held-out notes, the notes are soft-deleted in the copy (the app never does
    that), the files keep their shapes, the 40-note floor still refuses."""
    import os
    import random
    import subprocess

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.models.job import Job
    from app.models.note import Note
    from app.services import auth_service, note_service

    copy = tmp_path / "copy.db"
    engine = create_engine(f"sqlite:///{copy.as_posix()}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tenants = []
    for email, notes in (("big@example.com", PERSONAS["asha"]["notes"] + PERSONAS["chetan"]["notes"]),
                         ("small@example.com", PERSONAS["asha"]["notes"] + PERSONAS["chetan"]["notes"][:15])):
        user = auth_service.create_user(db, email=email, password="pw" * 8)
        user.tier = "studio"
        db.add(Job(id=f"job-{user.id[:8]}", tenant_id=user.id, job_type="topic", topic="t", status="completed"))
        db.commit()
        for text in notes:
            note_service.create_note(db, user.id, target_type="job", target_id=f"job-{user.id[:8]}", body_md=text)
        tenants.append(user.id)
    big, small = tenants
    notes = list(note_service.iter_notes(db, big, include_deleted=False))
    bodies = {n.id: n.body_md for n in notes}
    held = [n.id for n in random.Random(3304).sample(notes, 20)]
    db.close()
    engine.dispose()

    driver = tmp_path / "driver.py"
    driver.write_text(PAIRS_DRIVER, encoding="utf-8")
    out, key = tmp_path / "pairs.json", tmp_path / "key.json"
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    run = subprocess.run(
        [sys.executable, str(driver), str(copy), big, small, str(out), str(key), str(scripts), "voice_match_harness"],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(scripts.parent), "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    assert "refused: tier (iii) needs at least 40 live notes; this tenant has 39" in run.stdout
    assert f"wrote 20 pairs to {out} and the key to {key}. Show the user only the pairs file." in run.stdout

    pairs = json.loads(out.read_text(encoding="utf-8"))
    keys = json.loads(key.read_text(encoding="utf-8"))
    assert [k["note_id"] for k in keys] == held, "the harness's seed picks the notes"
    assert [p["pair"] for p in pairs] == [f"p{i:02d}" for i in range(1, 21)]
    for p, k in zip(pairs, keys):
        assert set(p) == {"pair", "A", "B"} and set(k) == {"pair", "own_is", "note_id", "topic"}
        assert p[k["own_is"]] == bodies[k["note_id"]]
        assert p["B" if k["own_is"] == "A" else "A"] == f"draft for {k['topic']}"
    engine = create_engine(f"sqlite:///{copy.as_posix()}")
    db = sessionmaker(bind=engine)()
    assert {n.id for n in db.query(Note).filter(Note.tenant_id == big, Note.deleted_at.isnot(None))} == set(held)
    db.close()
    engine.dispose()


def test_the_app_scores_the_fixture_as_the_script_does(tmp_path, unauthenticated_client, db, monkeypatch):
    """The same key and answers, scored by ``POST /echo/voice-test/{id}/score``."""
    import uuid

    from app.models.echo_voice_test import EchoVoiceTest
    from app.services import auth_service

    key = json.loads((USER_TEST / "key.json").read_text(encoding="utf-8"))
    answers = json.loads((USER_TEST / "answers.json").read_text(encoding="utf-8"))
    script = user_score(USER_TEST / "key.json", USER_TEST / "answers.json")

    user = auth_service.create_user(db, email=f"fx-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)
    user.tier = "studio"
    pairs = [{"pair": k["pair"], "A": f"text {k['pair']} A", "B": f"text {k['pair']} B"} for k in key]
    row = EchoVoiceTest(tenant_id=user.id, user_id=user.id, status="ready", seed=1, pairs_total=len(key), pairs_built=len(key),
                        pairs_json=json.dumps(pairs), key_json=json.dumps(key), picks_json=json.dumps(answers))
    db.add(row)
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    r = unauthenticated_client.post(f"/api/v1/echo/voice-test/{row.id}/score", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["test"]["result"] == {"pairs": script["pairs"], "picked_own": script["picked_own"],
                                     "picked_own_share": script["picked_own_share"], "passed": script["pass"]}
    assert (got["gate"]["status"], got["gate"]["pairs"], got["gate"]["picked_own_share"]) == ("passed", 20, 0.75)
