"""The voice test procedure (T-3.4.1.8), shared by the harness and the app.

What must hold:

- The pairs are the harness's: the same held-out notes for a seed, the same
  prompts in the same order, the same coin flips, the same shapes.
- Holding notes out in the app changes nothing in the live database, yet
  leaves exactly the signals and cadence an extraction run leaves after
  those notes are deleted (what ``user-pairs`` does on its copy), and the
  trait card ranks them as the harness's index does.
- A signal learned only from a held-out note never reaches the card: that
  would let the draft borrow from the very note it is paired with.
- Generation spends through one patched model, commits progress, and fails
  in words; a failed or stale test is never shown as pairs.
- A test runs on the model the user pinned for ``echo_draft``, and the row
  says so.
- Staleness is measured from the last progress, and a test marked failed
  stays failed: the worker stops spending and cannot turn it back to ready.
- The database, not the check before the insert, holds one open test per
  tenant.
"""
from __future__ import annotations

import json
import random
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.echo_voice_test import EchoVoiceTest
from app.models.job import Job
from app.models.user_llm_override import UserLLMOverride
from app.models.voice_signal import VoiceSignal
from app.models.voice_signal_input import VoiceSignalInput
from app.services import auth_service, note_service
from app.services import echo_personal_vectors as pv
from app.services import echo_signal_extraction as ex
from app.services import echo_signal_service as signals
from app.services import echo_voice_test_service as vt
from app.services.llm_routing import UseCaseConfig, resolve_config
from tests.usage_helpers import MeteredFakeChat

PERSONAS = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "echo_voice" / "personas.json").read_text(encoding="utf-8")
)["personas"]
#: 48 notes in two sharply different styles and languages (English, romanised
#: Hindi): which notes are held out shows in the cadence.
NOTES = PERSONAS["asha"]["notes"] + PERSONAS["chetan"]["notes"]


class FakeModel:
    """The draft model: a topic for a TOPIC prompt, a draft for a VOICE one."""

    def __init__(self, fail_on: int | None = None):
        self.prompts: list[str] = []
        self.fail_on = fail_on

    def __call__(self, prompt: str) -> tuple[str, int, int]:
        self.prompts.append(prompt)
        if self.fail_on is not None and len(self.prompts) == self.fail_on:
            raise RuntimeError("provider down")
        if prompt.startswith("In at most twelve words"):
            note = prompt.split("Note:\n", 1)[1]
            return f"topic: {note[:30]}", 40, 6
        situation = prompt.split("Situation:\n", 1)[1].split("\n", 1)[0]
        return f"A draft on {situation}", 900, 60


def _writer(db, notes=NOTES, tier="studio"):
    user = auth_service.create_user(db, email=f"vt-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)
    user.tier = tier
    job_id = f"job-{user.id[:8]}"
    db.add(Job(id=job_id, tenant_id=user.id, job_type="topic", topic="t", status="completed"))
    db.commit()
    for text in notes:
        note_service.create_note(db, user.id, target_type="job", target_id=job_id, body_md=text)
    return user


def _signal(db, tenant, value, sources, *, signal_type="vocabulary", suppressed=None):
    row = VoiceSignal(
        tenant_id=tenant, user_id=tenant, signal_type=signal_type, value=value, value_key=value.casefold(),
        weight=float(len(sources)), language="en", origin="llm", consent_version="1",
        derived_from=json.dumps(sources),
        examples_json=json.dumps([{"text": f"example from {s}", "source": s} for s in sources]),
        suppressed_at=suppressed, suppressed_reason="user" if suppressed else None,
    )
    db.add(row)
    db.commit()
    return row


def _snapshot(db, tenant):
    signals = sorted(
        (r.id, r.value, r.derived_from, r.examples_json, r.weight, r.suppressed_at, r.suppressed_reason)
        for r in db.query(VoiceSignal).filter(VoiceSignal.tenant_id == tenant)
    )
    ledger = sorted((r.source_ref, r.content_hash) for r in db.query(VoiceSignalInput).filter(VoiceSignalInput.tenant_id == tenant))
    return signals, ledger


# ---------------------------------------------------------------------------
# The procedure


def test_hold_out_keeps_the_pre_registered_floor_and_the_harness_sample():
    rng = random.Random(vt.SEED)
    with pytest.raises(vt.NotEnoughNotes, match="needs at least 40 live notes; this tenant has 39"):
        vt.hold_out(list(range(39)), rng)
    notes = list(range(48))
    assert vt.hold_out(notes, random.Random(vt.SEED)) == random.Random(vt.SEED).sample(notes, 20)


def test_build_pairs_is_the_harness_procedure():
    """Same prompts in the same order, the same coin flips, the same shapes."""
    held = [(f"n{i}", NOTES[i]) for i in range(3)]
    remaining = NOTES[3:]
    model = FakeModel()
    cards = []

    def card(topic):
        cards.append(topic)
        return ["style · vocabulary: plain words"]

    built = vt.build_pairs(held, remaining, ask=model, trait_card=card, rng=random.Random(7))

    flips = random.Random(7)
    exemplars = vt.exemplars(remaining)
    expected_prompts = []
    for i, (note_id, own) in enumerate(held, start=1):
        topic = f"topic: {own[:30]}"
        expected_prompts += [
            vt.TOPIC_PROMPT.format(note=own),
            vt.voice_prompt(["style · vocabulary: plain words"], exemplars, topic, "English"),
        ]
        own_first = flips.random() < 0.5
        draft = f"A draft on {topic}"
        assert built.pairs[i - 1] == {"pair": f"p{i:02d}", "A": own if own_first else draft, "B": draft if own_first else own}
        assert built.keys[i - 1] == {"pair": f"p{i:02d}", "own_is": "A" if own_first else "B", "note_id": note_id, "topic": topic}
    assert model.prompts == expected_prompts
    assert cards == [f"topic: {own[:30]}" for _, own in held], "the card is built for the note's topic"
    assert (built.tokens_in, built.tokens_out) == (3 * 940, 3 * 66)
    assert "- style · vocabulary: plain words" in model.prompts[1] and "[5] " in model.prompts[1]


def test_a_held_out_note_in_another_language_gets_a_pair():
    """The label indexes the prompt's language, so `other` must have a name,
    and until T-3.3.2.11 a Spanish note was drafted as romanised Hindi."""
    spanish = "Creo que los incentivos importan mas que las intenciones en este caso, y la gente responde a lo que le conviene."
    assert ex.language_of(spanish) == "other"
    model = FakeModel()

    built = vt.build_pairs([("n1", spanish)], NOTES, ask=model, trait_card=lambda topic: [], rng=random.Random(3))

    assert len(built.pairs) == 1
    instruction = model.prompts[-1].split("Write a short note", 1)[1]
    assert "the language of the situation above" in instruction and "Hindi" not in instruction
    assert set(vt.LANGUAGE_NAMES) == set(signals.LANGUAGES)


def test_the_other_wording_relies_on_the_topic_call_a_known_gap():
    """A gap, pinned. FakeModel echoes the note, so the test above cannot show
    it: TOPIC_PROMPT names no language and the drafter never sees the note, so
    an English topic leaves an `other` draft with only English to go on. Only a
    live run can say how often that happens; the comment on LANGUAGE_NAMES says
    what to do then."""
    spanish = "Creo que los incentivos importan mas que las intenciones en este caso, y la gente responde a lo que le conviene."
    assert "language" not in vt.TOPIC_PROMPT.lower()
    prompts: list[str] = []

    def answers_in_english(prompt: str) -> tuple[str, int, int]:
        prompts.append(prompt)
        return "Whether incentives outweigh intentions" if len(prompts) == 1 else "Un borrador", 1, 1

    vt.build_pairs([("n1", spanish)], NOTES, ask=answers_in_english, trait_card=lambda topic: [], rng=random.Random(3))

    draft_prompt = prompts[1]
    assert "Situation:\nWhether incentives outweigh intentions\n" in draft_prompt
    assert "in the language of the situation above reacting to this" in draft_prompt
    assert spanish not in draft_prompt


def test_score_picks_is_the_pre_registered_rule():
    keys = [{"pair": f"p{i:02d}", "own_is": "A" if i % 2 else "B"} for i in range(20)]
    own = {k["pair"]: k["own_is"] for k in keys}
    other = {k["pair"]: ("B" if k["own_is"] == "A" else "A") for k in keys}
    sixteen = {**own, **{k: other[k] for k in list(other)[:4]}}
    assert vt.score_picks(keys, sixteen) == {"pairs": 20, "picked_own_share": 0.8, "pass": True, "picked_own": 16}
    seventeen = {**own, **{k: other[k] for k in list(other)[:3]}}
    assert vt.score_picks(keys, seventeen)["pass"] is False
    assert vt.score_picks(keys[:19], own)["pass"] is False, "fewer than 20 pairs never passes"
    assert vt.score_picks([], {}) == {"pairs": 0, "picked_own_share": 1.0, "pass": False, "picked_own": 0}


# ---------------------------------------------------------------------------
# Holding out without touching the live database


def test_the_what_if_drops_what_only_held_out_notes_taught_and_changes_nothing(db):
    user = _writer(db)
    notes = list(note_service.iter_notes(db, user.id, include_deleted=False))
    ex.run(db, user.id, use_llm=False)  # the ledger, as a real run leaves it
    held, kept = notes[0], notes[1]
    only_held = _signal(db, user.id, "says 'honestly' a lot", [f"note:{held.id}"])
    mixed = _signal(db, user.id, "starts from first principles", [f"note:{held.id}", f"note:{kept.id}"])
    only_kept = _signal(db, user.id, "short paragraphs", [f"note:{kept.id}"])
    _signal(db, user.id, "rejected habit", [f"note:{kept.id}"], suppressed=vt._now())
    before = _snapshot(db, user.id)

    docs, cadence = vt.withdrawn_signals(db, user.id, [f"note:{held.id}"])

    texts = {vid: text for vid, text, _ in docs}
    assert pv.signal_vector_id(only_held.id) not in texts, "a signal only the held-out note taught is gone"
    assert pv.signal_vector_id(only_kept.id) in texts
    mixed_text = texts[pv.signal_vector_id(mixed.id)]
    assert f"note:{kept.id}" in mixed_text and f"note:{held.id}" not in mixed_text, "its held-out example is gone"
    assert not any("rejected habit" in t for t in texts.values())
    assert cadence, "the stylometry still runs over the kept notes"
    assert _snapshot(db, user.id) == before, "the live rows are exactly as they were"


def test_the_what_if_equals_deleting_the_notes_and_running_extraction(db):
    """What ``user-pairs`` does on its copy, done for real afterwards on the
    same database, leaves the same signals and cadence the what-if saw."""
    user = _writer(db)
    ex.run(db, user.id, use_llm=False)
    notes = list(note_service.iter_notes(db, user.id, include_deleted=False))
    held = vt.hold_out(notes, random.Random(11))
    kept = [n for n in notes if n not in held]
    for i, n in enumerate(held[:5]):
        _signal(db, user.id, f"held-only habit {i}", [f"note:{n.id}"])
        _signal(db, user.id, f"shared habit {i}", [f"note:{n.id}", f"note:{kept[i].id}"])
    _signal(db, user.id, "kept-only habit", [f"note:{kept[0].id}"])

    docs, cadence = vt.withdrawn_signals(db, user.id, [f"note:{n.id}" for n in held])
    # Mutation check: with nothing held out, the held-only habits stay, so
    # the comparison below can tell a what-if that withdrew from one that did not.
    unwithdrawn, _ = vt.withdrawn_signals(db, user.id, [])
    assert sum("held-only habit" in t for _, t, _ in unwithdrawn) == 5
    assert not any("held-only habit" in t for _, t, _ in docs)

    # The harness, on its copy.
    for n in held:
        note_service.delete_note(db, user.id, n.id)
    ex.run(db, user.id, use_llm=False)
    real = [(text, meta) for text, meta in pv.desired(db, user.id).values() if meta["kind"] == "signal"]

    def comparable(items):
        return sorted((t, json.dumps({k: v for k, v in m.items() if k not in ("row_id", "content_hash")}, sort_keys=True)) for t, m in items)

    assert comparable((t, m) for _, t, m in docs) == comparable(real)
    assert cadence == vt._cadence_values(db, user.id)


@pytest.fixture
def chroma(monkeypatch):
    monkeypatch.setattr(settings, "ECHO_PERSONAL_INDEX_ENABLED", True)
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield client
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def test_the_held_out_card_ranks_as_the_harness_index_does(db, chroma):
    user = _writer(db)
    ex.run(db, user.id, use_llm=False)
    notes = list(note_service.iter_notes(db, user.id, include_deleted=False))
    held = vt.hold_out(notes, random.Random(5))
    kept = [n for n in notes if n not in held]
    habits = ["loves cricket metaphors", "distrusts single-source claims", "writes about monsoon farming",
              "quotes old film songs", "argues from household budgets", "cites railway history"]
    for i, h in enumerate(habits):
        _signal(db, user.id, h, [f"note:{held[i].id}"] + ([f"note:{kept[i].id}"] if i % 2 else []), signal_type="topic_affinity")
    pv.sync_tenant(db, user.id)
    topics = ["the cricket season", "news from one source", "rain and crops", "a railway station"]

    card = vt.HeldOutTraitCard(db, user.id, [f"note:{n.id}" for n in held])
    try:
        app_cards = [card(t) for t in topics]
    finally:
        card.close()
    assert not any("loves cricket metaphors" in line for c in app_cards for line in c), "held-only signals never reach the card"

    for n in held:
        note_service.delete_note(db, user.id, n.id)
    ex.run(db, user.id, use_llm=False)
    pv.sync_tenant(db, user.id)
    assert app_cards == [vt.trait_card(db, user.id, t) for t in topics]
    names = {c if isinstance(c, str) else c.name for c in chroma.list_collections()}
    assert not any(n.startswith("voice_test_") for n in names), "the scratch collection is dropped"


# ---------------------------------------------------------------------------
# Generation


def _generating(db, user, **kw):
    row = EchoVoiceTest(tenant_id=user.id, user_id=user.id, status="generating", seed=kw.pop("seed", 42),
                        pairs_total=vt.PAIRS, model=kw.pop("model_name", "gpt-5.5"), **kw)
    db.add(row)
    db.commit()
    return row


def test_generate_writes_the_harness_pairs_for_the_test_seed(db):
    user = _writer(db)
    row = _generating(db, user, seed=1234)
    notes = list(note_service.iter_notes(db, user.id, include_deleted=False))
    model = FakeModel()

    vt.generate(db, row.id, ask=model)

    db.refresh(row)
    assert row.status == "ready" and row.pairs_built == 20 and row.ready_at is not None
    rng = random.Random(1234)
    held = vt.hold_out(notes, rng)
    keys = json.loads(row.key_json)
    assert [k["note_id"] for k in keys] == [n.id for n in held]
    pairs = json.loads(row.pairs_json)
    for p, k, n in zip(pairs, keys, held):
        assert p[k["own_is"]] == n.body_md
        assert p["B" if k["own_is"] == "A" else "A"].startswith("A draft on topic: ")
    assert len(model.prompts) == 40
    assert (row.tokens_in, row.tokens_out) == (20 * 940, 20 * 66) and row.cost_usd > 0
    exemplar_block = model.prompts[1].split("Things they wrote:\n", 1)[1].split("\n\nSituation:", 1)[0]
    assert not any(n.body_md in exemplar_block for n in held), "no held-out note is an exemplar"


def test_generate_fails_in_words_and_shows_nothing(db):
    user = _writer(db)
    row = _generating(db, user)
    vt.generate(db, row.id, ask=FakeModel(fail_on=7))
    db.refresh(row)
    assert row.status == "failed" and "could not write the test" in row.error
    assert vt.to_dict(row)["pairs"] == []

    few = _writer(db, notes=NOTES[:39])
    row = _generating(db, few)
    model = FakeModel()
    vt.generate(db, row.id, ask=model)
    db.refresh(row)
    assert row.status == "failed" and "40 of your notes" in row.error and model.prompts == []


def test_the_draft_model_is_echo_draft_called_as_the_harness_calls_its_drafter(db, monkeypatch):
    from langchain_core.messages import AIMessage

    from app.services.llm_routing import USE_CASE_REGISTRY

    replies = [RuntimeError("blip"), "   ", "  a draft  ", RuntimeError("a"), RuntimeError("b"), RuntimeError("c")]
    built = {}

    class Client:
        def invoke(self, messages):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return AIMessage(content=reply, usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10})

    def get_llm_for(use_case, temperature=0.0, max_tokens=None, *, tenant_id=None, db=None):
        built.update(use_case=use_case, temperature=temperature, max_tokens=max_tokens, tenant_id=tenant_id, db=db)
        return Client()

    monkeypatch.setattr("app.services.llm_service.get_llm_for", get_llm_for)
    monkeypatch.setattr(vt.time, "sleep", lambda s: None)
    ask = vt._drafter(db, "tenant-1")
    assert built == {"use_case": "echo_draft", "temperature": 1.0, "max_tokens": 1200, "tenant_id": "tenant-1", "db": db}
    assert ask("p") == ("a draft", 7, 3), "a failed try and an empty reply are both retried"
    with pytest.raises(RuntimeError, match="c"):
        ask("p")

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from voice_match_harness import DRAFTER

    default = USE_CASE_REGISTRY["echo_draft"].default_config
    assert (default.provider, default.model, default.reasoning) == DRAFTER, "the app tests the drafter the gate was measured on"


def test_a_test_that_lost_its_worker_reads_as_failed(db):
    user = _writer(db, notes=NOTES[:2])
    row = _generating(db, user)
    row.created_at = vt._now() - vt.STALE_AFTER - timedelta(minutes=1)
    db.commit()
    assert vt.latest(db, user.id).status == "failed"
    assert "stopped before it finished" in vt.get_test(db, user.id, row.id).error


def test_the_key_never_leaves_through_to_dict(db):
    user = _writer(db)
    row = _generating(db, user)
    vt.generate(db, row.id, ask=FakeModel())
    db.refresh(row)
    shown = json.dumps(vt.to_dict(row), default=str)
    assert "own_is" not in shown and "note_id" not in shown and "key" not in vt.to_dict(row)


def _poll_gives_up(db, test_id):
    """What the page's poll does to a silent test, from its own session: the
    worker's session does not see it happen."""
    other = Session(bind=db.get_bind())
    try:
        vt._fail(other, test_id, "Writing the test stopped before it finished. Start a new one.")
    finally:
        other.close()


# ---------------------------------------------------------------------------
# The user's own model (D-041, E-1.13)


PINNED = UseCaseConfig("local", "qwen/qwen3-9b", "off")


def _pin(db, user, cfg=PINNED):
    db.add(UserLLMOverride(user_id=user.id, use_case=vt.USE_CASE, provider=cfg.provider, model=cfg.model, reasoning=cfg.reasoning))
    db.commit()


@pytest.fixture
def clients(monkeypatch):
    """The config of each client the real ``get_llm_for`` builds. Only the
    provider client is fake: resolving the config stays production code."""
    built = []

    def build(cfg, temperature, max_tokens, *, byok_api_key=None):
        built.append(cfg)
        return MeteredFakeChat(reply="some words")

    monkeypatch.setattr("app.services.llm_service._build_from_config", build)
    return built


def test_a_test_runs_on_the_model_the_user_pinned(db, clients):
    """Their notes go only where they said. The worker has no request around
    it, so nothing but ``generate`` can load the user's overrides."""
    user = _writer(db)
    _pin(db, user)
    row = _generating(db, user)

    vt.generate(db, row.id)

    db.refresh(row)
    assert row.status == "ready"
    assert clients == [PINNED], "every call went to the pinned model, not the install's"
    assert row.model == PINNED.model, "the row names the model that ran"
    assert row.tokens_in > 0 and row.cost_usd == 0.0, "priced as the pinned model, not as the install's"


def test_a_user_without_a_pin_runs_on_the_install_model(db, clients):
    user = _writer(db)
    row = _generating(db, user, model_name="an old name")
    vt.generate(db, row.id)
    db.refresh(row)
    assert clients == [resolve_config(vt.USE_CASE)]
    assert row.model == resolve_config(vt.USE_CASE).model


def test_the_pin_stays_with_the_test(db, clients):
    """The override is loaded for the block, not left on the worker for the
    next user's task."""
    user = _writer(db)
    _pin(db, user)
    vt.generate(db, _generating(db, user).id)
    assert resolve_config(vt.USE_CASE) != PINNED


# ---------------------------------------------------------------------------
# Staleness and a test closed under the worker


def test_staleness_runs_from_the_last_progress_not_the_start(db):
    user = _writer(db, notes=NOTES[:2])
    row = _generating(db, user)
    row.created_at = vt._now() - vt.STALE_AFTER - timedelta(hours=1)
    row.last_progress_at = vt._now() - vt.STALE_AFTER + timedelta(minutes=1)
    db.commit()
    assert vt.latest(db, user.id).status == "generating", "a slow test that is moving is not lost"
    assert vt.get_test(db, user.id, row.id).status == "generating"

    row.last_progress_at = vt._now() - vt.STALE_AFTER - timedelta(minutes=1)
    db.commit()
    assert vt.get_test(db, user.id, row.id).status == "failed", "silent for too long: its worker is gone"


def test_the_time_in_the_queue_does_not_count_once_the_worker_starts(db):
    """A long report ahead of it on a solo pool: the test starts late, then
    the clock runs from there."""
    user = _writer(db)
    row = _generating(db, user)
    row.created_at = vt._now() - vt.STALE_AFTER - timedelta(minutes=1)
    db.commit()
    model = FakeModel()
    seen = []

    def ask(prompt):
        if not seen:
            other = Session(bind=db.get_bind())
            seen.append(vt.latest(other, user.id).status)
            other.close()
        return model(prompt)

    vt.generate(db, row.id, ask=ask)

    assert seen == ["generating"]
    db.refresh(row)
    assert row.status == "ready" and row.error is None


def test_a_test_marked_failed_stays_failed_and_stops_spending(db):
    user = _writer(db)
    row = _generating(db, user)
    message = "Writing the test stopped before it finished. Start a new one."
    model = FakeModel()

    def ask(prompt):
        if len(model.prompts) == 4:
            _poll_gives_up(db, row.id)
        return model(prompt)

    result = vt.generate(db, row.id, ask=ask)

    assert len(model.prompts) == 6, "the pair in flight finishes; the other 17 are never asked for"
    assert result.status == "failed"
    db.refresh(row)
    assert (row.status, row.error, row.pairs_built, row.ready_at) == ("failed", message, 2, None)
    assert (row.pairs_json, row.key_json) == ("[]", "[]"), "no pairs and no key on a closed test"


def test_the_last_write_cannot_turn_a_failed_test_back_to_ready(db, monkeypatch):
    """The poll gives up after the last pair's progress, before the pairs are
    stored."""
    user = _writer(db)
    row = _generating(db, user)
    real = vt.build_pairs

    def then_give_up(*args, **kwargs):
        built = real(*args, **kwargs)
        _poll_gives_up(db, row.id)
        return built

    monkeypatch.setattr(vt, "build_pairs", then_give_up)
    vt.generate(db, row.id, ask=FakeModel())

    db.refresh(row)
    assert row.status == "failed" and row.ready_at is None
    assert (row.pairs_json, row.key_json) == ("[]", "[]")


def test_a_failure_cannot_overwrite_a_test_that_got_written(db):
    """The poll read "generating" just before the worker finished."""
    user = _writer(db)
    row = _generating(db, user)
    vt.generate(db, row.id, ask=FakeModel())
    _poll_gives_up(db, row.id)
    db.refresh(row)
    assert row.status == "ready" and row.error is None


def test_a_test_closed_while_queued_is_never_written(db):
    user = _writer(db)
    row = _generating(db, user)
    _poll_gives_up(db, row.id)
    db.expire_all()  # a worker's session is new, and reads what the poll wrote
    model = FakeModel()
    vt.generate(db, row.id, ask=model)
    assert model.prompts == []


# ---------------------------------------------------------------------------
# One open test per tenant


def test_the_database_holds_one_open_test_per_tenant(db):
    user = _writer(db, notes=[])
    other = _writer(db, notes=[])
    _generating(db, user)

    def another(status, owner=user):
        return EchoVoiceTest(tenant_id=owner.id, user_id=owner.id, status=status, seed=1, pairs_total=vt.PAIRS)

    for status in ("generating", "ready"):
        db.add(another(status))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    db.add_all([another("scored"), another("scored"), another("failed"), another("ready", owner=other)])
    db.commit()
