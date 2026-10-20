"""Signal extraction over export imports (T-3.3.2.10).

A WhatsApp import can be 100k turns. It must count as ONE input: one ledger
row, one stylometric profile over every own-words turn, and a capped,
time-spread sample for the model, whose examples cite the turns themselves
so undoing the import withdraws them. Context-only turns (the other person's)
never reach any of it (D-089).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.models.share import Share
from app.models.voice_signal import VoiceSignal
from app.models.voice_signal_input import VoiceSignalInput
from app.services import auth_service, echo_intake_service, echo_signal_service
from app.services import echo_signal_extraction as ex
from app.services import echo_stylometry as stylo

T0 = datetime(2016, 1, 1)


def _user(db):
    u = auth_service.create_user(db, email=f"imp-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)
    u.tier = "studio"
    db.commit()
    return u


def _import(db, user, n_turns: int, *, days: int = 3650) -> str:
    """A synthetic chat: alternating turns, the user's own on even turns."""
    import_id = str(uuid.uuid4())
    rows = []
    for k in range(n_turns):
        own = k % 2 == 0
        words = "ok" if k % 10 == 0 else f"turn {k} says base rates matter before any story is believed"
        rows.append({
            "id": str(uuid.uuid4()), "tenant_id": user.id, "user_id": user.id,
            "surface": "file_import", "content_type": "chat_turn",
            "raw_payload_json": "{}", "extracted_text": ("MINE " if own else "THEIRS ") + words,
            "author_is_tenant": own, "processing_state": "pending",
            "import_id": import_id, "occurred_at": T0 + timedelta(days=days * k / max(1, n_turns - 1)),
        })
    db.bulk_insert_mappings(Share, rows)
    db.commit()
    return import_id


def test_an_import_is_one_input_with_a_spread_capped_sample(db, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SIGNALS_IMPORT_SAMPLE", 50)
    user = _user(db)
    import_id = _import(db, user, 2000)
    inputs = ex.gather_inputs(db, user.id)
    assert [i.ref for i in inputs] == [f"import:{import_id}"]
    imp = inputs[0]
    assert imp.kind == "import" and "THEIRS" not in imp.text, "the other person's turns never count"
    assert len(imp.passages) == 50
    assert all(p.ref.startswith("share:") and p.text.startswith("MINE") for p in imp.passages)
    assert all(len(stylo.words(p.text)) >= settings.ECHO_SIGNALS_MIN_PASSAGE_WORDS for p in imp.passages), "no 'ok' turns"
    years = {p.at[:4] for p in imp.passages}
    assert {"2016", "2025"} <= years, "the sample spans the chat, not its last month"
    assert ex.quick_new_count(db, user.id) == 1, "an import is one new input, not 1,000"


def test_a_run_writes_one_ledger_row_and_cites_turns(db, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SIGNALS_IMPORT_SAMPLE", 40)
    user = _user(db)
    import_id = _import(db, user, 400)
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        pids = re.findall(r"\[(P\d+)\]", prompt)[:3]
        return json.dumps({"signals": [{"signal_type": "methodology", "value": "Checks base rates first",
                                        "examples": [{"id": pid, "quote": "base rates matter before any story is believed"} for pid in pids]}]}), 100, 50

    report = ex.run(db, user.id, llm=llm, model="gpt-5.6-luna")
    assert report.inputs_read == 1
    assert sum(p.count("[P") for p in prompts) == 40, "the model read the sample, not 200 turns"
    ledger = db.query(VoiceSignalInput).filter(VoiceSignalInput.tenant_id == user.id).all()
    assert [(r.source_ref, r.kind, r.llm_done) for r in ledger] == [(f"import:{import_id}", "import", True)]

    sig = next(r for r in echo_signal_service.list_signals(db, user.id) if r.signal_type == "methodology")
    cited = json.loads(sig.derived_from)
    assert cited and all(ref.startswith("share:") for ref in cited)
    for ref in cited:
        share = db.get(Share, ref.split(":", 1)[1])
        assert sig.id in json.loads(share.derived_signal_ids_json), "each cited turn records its signal"
    assert ex.quick_new_count(db, user.id) == 0
    assert ex.run(db, user.id, llm=llm, model="m").inputs_read == 0, "nothing new: nothing read"


@pytest.fixture
def chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    yield
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def test_undoing_an_import_withdraws_its_turns_and_its_ledger_row(db, chroma, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ECHO_SIGNALS_IMPORT_SAMPLE", 20)
    user = _user(db)
    import_id = _import(db, user, 100)

    def llm(prompt):
        pid = re.findall(r"\[(P\d+)\]", prompt)[0]
        return json.dumps({"signals": [{"signal_type": "methodology", "value": "Checks base rates first",
                                        "examples": [{"id": pid, "quote": "base rates matter before any story is believed"}]}]}), 1, 1

    ex.run(db, user.id, llm=llm, model="m")
    sig = next(r for r in echo_signal_service.list_signals(db, user.id) if r.signal_type == "methodology")

    ids = [r[0] for r in db.query(Share.id).filter(Share.import_id == import_id)]
    echo_intake_service.delete_shares(db, user.id, ids)
    db.expire_all()
    assert db.get(VoiceSignal, sig.id).suppressed_reason == "source_deleted"

    ex.run(db, user.id, use_llm=False)
    assert db.query(VoiceSignalInput).filter(VoiceSignalInput.tenant_id == user.id).count() == 0


def test_stylometry_reads_every_own_turn_and_the_mean_is_exact():
    p = stylo.combine(stylo.profile(f"word {'x ' * (k % 7)}end.") for k in range(1000))
    back = stylo.StyleProfile.from_json(json.loads(json.dumps(p.to_json())))
    assert len(back.sentence_lengths) == 400, "the ledger keeps a capped list"
    assert back.mean_sentence_words == pytest.approx(p.sentence_words / p.n_sentences), "but the mean is exact"
