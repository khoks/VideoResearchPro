"""The user-as-judge voice test, tier (iii) of D-100, for the harness and the app (T-3.4.1.8).

**The test.** Pre-registered in docs/notes/2026-10-19-voice-match-preregistration.md:
hold out 20 of the user's live notes (at least 40 are needed), learn their
voice from the rest, write a draft in that voice on each held-out note's
topic, and show each draft beside the note in random order. The user picks
the one they wrote. It passes when they pick their own text in at most 80%
of at least 20 pairs, so a draft is taken for theirs at least one time in
five. A pass switches "speak as me" on for them (D-102) through
``echo_voice_gates``.

**One procedure, two callers.**

- ``scripts/voice_match_harness.py user-pairs`` and ``user-score --record``:
  the operator's command line. It holds the notes out by soft-deleting them
  in a COPY of the database and re-running extraction there. What it writes
  and prints is unchanged.
- The Echo page (``/echo/voice-test``): the same pairs, prompts and score,
  against the live database, which it must not change. The held-out notes
  leave the trait card through a what-if. The database half of an
  extraction run with those notes gone (``apply_pending`` and
  ``sync_stylometry``, the code the harness runs on its copy) runs in a
  transaction that is always rolled back. The signals that survive are then
  ranked in a throwaway in-memory Chroma collection, as the harness ranks
  them in its scratch one.

Both use ``hold_out`` (the sample and the 40-note floor), ``exemplars``,
the TOPIC and VOICE prompts, ``build_pairs`` (a topic call and a draft call
per pair, then the coin flip for the order), ``score_picks`` (the
``user-score`` rule) and ``echo_draft_service.record_voice_test`` (what
``--record`` writes).

The app differs from the harness in two ways:

- The model is the ``echo_draft`` use case, resolved for the user inside
  ``llm_service.byok_context``: their pin on /account/ai-models, their BYOK
  key, and metered as "Speak as me" usage. Its default is the harness's
  drafter (gpt-5.5, reasoning low), called with the harness's temperature
  (1.0) and output cap (1,200). Whoever moves ``echo_draft`` to another
  model tests the drafts they will get: ``echo_draft_service.draft`` resolves
  it the same way.
- Texts Echo has not learned from yet are not learned during the test. The
  harness's run reads them with the extraction model; here their stylometry
  counts and nothing else.

**Gates to start a test**, in order, each in words: the install switch and
readiness (the messages of ``GET /echo/draft/status``), 40 live notes, no
test already open, and ``ECHO_VOICE_TESTS_PER_DAY``. The tier
(``echo_speak_as_me``) is the router's 403. Only the user's click starts a
test, after the page has said it makes about 40 model calls. Those checks
read and then insert, so the rule of one open test is held by a partial
unique index, which turns the loser of a race into the same conflict.

**A test closed under the worker stays closed.** The page's poll marks a
test failed when the worker has said nothing for ``STALE_AFTER``. Everything
that writes to a generating test goes through ``_update_if_generating``, so
the check and the write are one statement: a worker that was only slow
finds out at its next pair, stops spending, and cannot turn the test back
to ready.
"""
from __future__ import annotations

import json
import logging
import random
import secrets
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Iterator

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.echo_voice_test import OPEN_STATUSES, EchoVoiceTest
from app.models.user import User
from app.models.voice_signal import VoiceSignal

logger = logging.getLogger(__name__)

#: The harness's fixed seed. The app draws a fresh one per test, so a retake
#: holds out different notes.
SEED = 3304
#: Pre-registered: at least 20 pairs, from a user with at least 40 live notes.
PAIRS = 20
MIN_NOTES = 40
#: The trait card's nearest signals, as the harness and S-3.4.1 read them.
TRAIT_CARD_SIGNALS = 8
#: The draft model: the harness's DRAFTER settings, on the use case that
#: has the same default.
USE_CASE = "echo_draft"
DRAFT_TEMPERATURE = 1.0
DRAFT_MAX_TOKENS = 1200
#: A test "generating" that has shown no progress for this long lost its
#: worker. Well above a slow pair: two calls of three tries each.
STALE_AFTER = timedelta(minutes=30)

LANGUAGE_NAMES = {
    "en": "English",
    "hi-Deva": "Hindi",
    "hi-Latn": "Hindi in Roman letters",
    "mixed": "Hinglish",
    # `language_of` could not name it. This relies on the topic call answering in
    # the note's language, which TOPIC_PROMPT does not ask for and, being fixed by
    # the pre-registration, cannot. Unchecked on a real note: an English topic
    # gets an English draft beside the user's note, and the pair gives itself
    # away. If a live run shows that, hold `other` notes out of the pairs.
    "other": "the language of the situation above",
}

# ---------------------------------------------------------------------------
# Prompts (fixed by the pre-registration)

TOPIC_PROMPT = """In at most twelve words, name the topic of this note, as a situation someone could react to. Reply with the topic only.

Note:
{note}"""

VOICE_PROMPT = """You are drafting a note as a specific person, in their voice. Below is what is known about how they write and think, and five things they actually wrote. Match their style: word choice, sentence length, punctuation, register, and the way they frame a point. Do not copy their sentences and do not mention the samples.

How they write and think:
{trait_card}

Things they wrote:
{exemplars}

Situation:
{situation}

Write a short note of 40 to 90 words in {language} reacting to this, as this person. Reply with the note only."""


def voice_prompt(card: list[str], exemplar_texts: list[str], situation: str, language: str) -> str:
    return VOICE_PROMPT.format(
        trait_card="\n".join(f"- {line}" for line in card) or "- (nothing learned yet)",
        exemplars="\n\n".join(f"[{i + 1}] {e}" for i, e in enumerate(exemplar_texts)),
        situation=situation,
        language=language,
    )


# ---------------------------------------------------------------------------
# The procedure, shared with the harness


class NotEnoughNotes(ValueError):
    pass


def hold_out(notes: list[Any], rng: random.Random, n: int = PAIRS) -> list[Any]:
    """The notes the test sets aside, drawn from ``rng`` before anything else."""
    if len(notes) < MIN_NOTES:
        raise NotEnoughNotes(f"tier (iii) needs at least {MIN_NOTES} live notes; this tenant has {len(notes)}")
    return rng.sample(notes, n)


def exemplars(notes: list[str], k: int = 5) -> list[str]:
    """Style diversity, not topic: spread over the mean-sentence-length range."""
    from app.services import echo_stylometry as stylo

    ranked = sorted(notes, key=lambda t: stylo.profile(t).mean_sentence_words)
    if len(ranked) <= k:
        return ranked
    idx = sorted({round(i * (len(ranked) - 1) / (k - 1)) for i in range(k)})
    return [ranked[i] for i in idx]


def card_lines(hit_texts: Iterable[str], cadence_values: Iterable[str]) -> list[str]:
    """The trait card: each nearest signal without its examples, then every
    cadence the stylometry found."""
    lines = [t.split("\nExamples:")[0] for t in hit_texts]
    for value in cadence_values:
        line = f"style · cadence: {value}"
        if line not in lines:
            lines.append(line)
    return lines


def _cadence_values(db: Session, tenant_id: str) -> list[str]:
    return [
        c.value
        for c in db.query(VoiceSignal)
        .filter(VoiceSignal.tenant_id == tenant_id, VoiceSignal.signal_type == "cadence", VoiceSignal.suppressed_at.is_(None))
        .all()
    ]


def trait_card(db: Session, tenant_id: str, situation: str) -> list[str]:
    """The harness's card, from the live personal index (on its copy, after
    the held-out notes were withdrawn)."""
    from app.services import echo_personal_vectors as pv

    hits = pv.query_personal_context(tenant_id, situation, n=TRAIT_CARD_SIGNALS, kinds=["signal"])
    return card_lines((h.text for h in hits), _cadence_values(db, tenant_id))


#: prompt -> (text, input tokens, output tokens)
Ask = Callable[[str], tuple[str, int, int]]


@dataclass
class PairSet:
    #: [{pair, A, B}]: what the user sees.
    pairs: list[dict] = field(default_factory=list)
    #: [{pair, own_is, note_id, topic}]: which side is theirs.
    keys: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


def build_pairs(
    held: list[tuple[str, str]],
    remaining: list[str],
    *,
    ask: Ask,
    trait_card: Callable[[str], list[str]],
    rng: random.Random,
    on_pair: Callable[[int], None] | None = None,
) -> PairSet:
    """One pair per held-out ``(note_id, text)``: name the note's topic, draft
    on that topic in the user's voice (trait card plus five exemplars from
    ``remaining``), then flip ``rng`` for which side the user's text is on."""
    from app.services.echo_signal_extraction import language_of

    shown = exemplars(remaining)
    out = PairSet()
    for i, (note_id, own) in enumerate(held, start=1):
        topic, t_in, t_out = ask(TOPIC_PROMPT.format(note=own))
        language = language_of(own)
        card = trait_card(topic)
        draft, d_in, d_out = ask(voice_prompt(card, shown, topic, LANGUAGE_NAMES[language]))
        own_first = rng.random() < 0.5
        pid = f"p{i:02d}"
        out.pairs.append({"pair": pid, "A": own if own_first else draft, "B": draft if own_first else own})
        out.keys.append({"pair": pid, "own_is": "A" if own_first else "B", "note_id": note_id, "topic": topic})
        out.tokens_in += t_in + d_in
        out.tokens_out += t_out + d_out
        if on_pair is not None:
            on_pair(i)
    return out


def score_picks(keys: list[dict], answers: dict[str, str]) -> dict:
    """``keys``: [{pair, own_is}]; ``answers``: {pair: "A" | "B"}. The
    pre-registered rule: pass when the user picks their own text in at most
    80% of pairs, over at least 20. A pair without an answer is not a pick
    of their own text."""
    from app.services.echo_draft_service import VOICE_TEST_MAX_OWN_SHARE, VOICE_TEST_MIN_PAIRS

    picked_own = sum(1 for row in keys if answers.get(row["pair"]) == row["own_is"])
    share = picked_own / len(keys) if keys else 1.0
    return {
        "pairs": len(keys),
        "picked_own_share": round(share, 3),
        "pass": len(keys) >= VOICE_TEST_MIN_PAIRS and share <= VOICE_TEST_MAX_OWN_SHARE,
        "picked_own": picked_own,
    }


# ---------------------------------------------------------------------------
# Holding notes out without changing the live database


@contextmanager
def _rolled_back(db: Session) -> Iterator[Session]:
    """A session whose every change is thrown away: its own connection, one
    transaction rolled back at the end, and ``rollback_only`` so that a
    commit inside cannot end that transaction early."""
    conn = db.get_bind().connect()
    trans = conn.begin()
    scratch = Session(bind=conn, autoflush=False, join_transaction_mode="rollback_only")
    try:
        yield scratch
    finally:
        scratch.close()
        trans.rollback()
        conn.close()


def withdrawn_signals(db: Session, tenant_id: str, held_refs: Iterable[str]) -> tuple[list[tuple[str, str, dict]], list[str]]:
    """The tenant's signals as an extraction run leaves them once the held-out
    texts are gone: ``(vector id, text, metadata)`` for each live signal, as
    the personal index would store it, and the cadence values. Read in a
    transaction that is rolled back, so the live rows are untouched. The texts
    are gathered before the first write, so on SQLite the write lock is held
    only for the withdrawal and the stylometry, not for reading every input."""
    from app.services import echo_personal_vectors as pv
    from app.services import echo_signal_extraction as ex

    held = set(held_refs)
    with _rolled_back(db) as s:
        inputs = [i for i in ex.gather_inputs(s, tenant_id) if i.ref not in held]
        state = ex.pending(s, tenant_id, inputs)
        ex.apply_pending(s, tenant_id, state)
        ex.sync_stylometry(s, tenant_id, {i.ref: i for i in inputs}, ex.MergeCounts())
        s.flush()
        docs = [(vid, text, meta) for vid, (text, meta) in pv.desired(s, tenant_id).items() if meta.get("kind") == "signal"]
        cadence = _cadence_values(s, tenant_id)
    return docs, cadence


class _ScratchIndex:
    """The signals as the harness's scratch Chroma holds them after its sync:
    an in-memory collection, created as ``echo_personal_vectors`` creates the
    real one and queried as ``query_personal_context`` queries it, deleted
    after the test is written. With the personal index off it is empty, as
    the harness's would be."""

    def __init__(self, docs: list[tuple[str, str, dict]]):
        from app.services import echo_personal_vectors as pv

        self._client: Any = None
        self._col: Any = None
        self._name = f"voice_test_{uuid.uuid4().hex}"
        if not docs or not pv.enabled():
            return
        import chromadb

        from app.services import echo_vectors

        self._client = chromadb.EphemeralClient()
        self._col = self._client.create_collection(
            name=self._name,
            metadata={"scope": "echo_personal_context"},
            embedding_function=echo_vectors._embedding_function(),  # noqa: SLF001
        )
        self._col.upsert(ids=[d[0] for d in docs], documents=[d[1] for d in docs], metadatas=[d[2] for d in docs])
        self._count = len(docs)

    def query(self, text: str, n: int) -> list[str]:
        if self._col is None or not text.strip():
            return []
        res = self._col.query(query_texts=[text], n_results=min(n, self._count), include=["documents"])
        return list(res["documents"][0])

    def close(self) -> None:
        if self._col is None:
            return
        try:
            self._client.delete_collection(self._name)
        except Exception:  # noqa: BLE001
            logger.warning("voice test: could not drop scratch collection %s", self._name, exc_info=True)
        self._col = None


class HeldOutTraitCard:
    """``trait_card`` for the app: the same lines, from the signals that
    survive withdrawing the held-out notes."""

    def __init__(self, db: Session, tenant_id: str, held_refs: Iterable[str]):
        docs, self.cadence = withdrawn_signals(db, tenant_id, held_refs)
        self._index = _ScratchIndex(docs)

    def __call__(self, situation: str) -> list[str]:
        return card_lines(self._index.query(situation, TRAIT_CARD_SIGNALS), self.cadence)

    def close(self) -> None:
        self._index.close()


# ---------------------------------------------------------------------------
# The app flow


class VoiceTestBlocked(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class VoiceTestConflict(VoiceTestBlocked):
    pass


class VoiceTestNotFound(LookupError):
    pass


class _TestClosed(Exception):
    """The test stopped being ``generating`` while the worker was on it."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _update_if_generating(db: Session, test_id: str, **values: Any) -> bool:
    """Write to a test only if it is still ``generating``, and count that as
    progress. The check and the write are one statement, and it commits.
    False: the test was closed, and nothing was written."""
    written = (
        db.query(EchoVoiceTest)
        .filter(EchoVoiceTest.id == test_id, EchoVoiceTest.status == "generating")
        .update({**values, "last_progress_at": _now()}, synchronize_session=False)
    )
    db.commit()
    return written > 0


def _fail(db: Session, test_id: str, message: str) -> EchoVoiceTest | None:
    """Mark a generating test failed. One that has been written or closed
    meanwhile stays as it is."""
    db.rollback()
    _update_if_generating(db, test_id, status="failed", error=message[:500])
    return db.get(EchoVoiceTest, test_id)


def _lost_its_worker(row: EchoVoiceTest) -> bool:
    return row.status == "generating" and (row.last_progress_at or row.created_at) < _now() - STALE_AFTER


def _open_message(row: EchoVoiceTest) -> str:
    return "Your test is being written." if row.status == "generating" else "Finish the test you started first."


def latest(db: Session, tenant_id: str) -> EchoVoiceTest | None:
    """The tenant's newest test. One that has shown no progress for a long
    time lost its worker: it is marked failed so a new one can start."""
    row = (
        db.query(EchoVoiceTest).filter(EchoVoiceTest.tenant_id == tenant_id)
        .order_by(EchoVoiceTest.created_at.desc(), EchoVoiceTest.id.desc()).first()
    )
    if row is not None and _lost_its_worker(row):
        return _fail(db, row.id, "Writing the test stopped before it finished. Start a new one.")
    return row


def get_test(db: Session, tenant_id: str, test_id: str) -> EchoVoiceTest:
    row = db.get(EchoVoiceTest, test_id)
    if row is None or row.tenant_id != tenant_id:
        raise VoiceTestNotFound(test_id)
    if _lost_its_worker(row):
        row = _fail(db, row.id, "Writing the test stopped before it finished. Start a new one.")
    return row  # type: ignore[return-value]


def tests_today(db: Session, tenant_id: str) -> int:
    start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.query(EchoVoiceTest).filter(EchoVoiceTest.tenant_id == tenant_id, EchoVoiceTest.created_at >= start).count()


def offer(db: Session, user: User) -> dict:
    """Whether the user may start a test now, and what one costs, in words.
    The install switch and readiness reuse the draft gate's codes and
    messages, so the page can show each reason once."""
    from app.services import echo_draft_service as drafts
    from app.services import llm_service
    from app.services.llm_routing import resolve_config

    st = drafts.status(db, user)
    blockers = [b for b in st.blockers if b["code"] in ("install_off", "not_ready")]
    notes = st.voice_gate["notes_total"]
    if notes < MIN_NOTES:
        blockers.append({
            "code": "notes_needed",
            "message": (
                f"The test needs {MIN_NOTES} of your notes: it sets {PAIRS} aside and learns your voice from the rest. "
                f"You have {notes}."
            ),
        })
    current = latest(db, user.id)
    if current is not None and current.status in OPEN_STATUSES:
        blockers.append({"code": "test_open", "message": _open_message(current)})
    cap = settings.ECHO_VOICE_TESTS_PER_DAY
    used = tests_today(db, user.id)
    if cap > 0 and used >= cap:
        blockers.append({"code": "daily_limit", "message": f"You have started {cap} voice tests today. Try again tomorrow."})
    # The model this user's test would run on: their pin, if they have one.
    with llm_service.byok_context(user.id, db):
        model = resolve_config(USE_CASE).model
    return {
        "available": not blockers,
        "blockers": blockers,
        "pairs": PAIRS,
        "model_calls": 2 * PAIRS,
        "model": model,
        "notes": notes,
        "notes_needed": MIN_NOTES,
        "pass_share": drafts.VOICE_TEST_MAX_OWN_SHARE,
        "tests_today": used,
        "tests_per_day": cap,
    }


def to_dict(row: EchoVoiceTest) -> dict:
    """The test as the page sees it. The pairs are shown while it is open;
    which side is the user's own never leaves the server."""
    result = None
    if row.status == "scored" and row.picked_own is not None:
        result = {
            "pairs": row.pairs_total,
            "picked_own": row.picked_own,
            "picked_own_share": round(row.picked_own / row.pairs_total, 3) if row.pairs_total else None,
            "passed": bool(row.passed),
        }
    return {
        "id": row.id,
        "status": row.status,
        "pairs_total": row.pairs_total,
        "pairs_built": row.pairs_built,
        "pairs": json.loads(row.pairs_json or "[]") if row.status == "ready" else [],
        "picks": json.loads(row.picks_json or "{}"),
        "result": result,
        "error": row.error,
        "model": row.model,
        "cost_usd": row.cost_usd,
        "created_at": row.created_at,
        "ready_at": row.ready_at,
        "scored_at": row.scored_at,
    }


def overview(db: Session, user: User) -> dict:
    from app.services import echo_draft_service as drafts

    off = offer(db, user)
    current = latest(db, user.id)
    return {"offer": off, "gate": drafts.voice_gate(db, user.id), "test": to_dict(current) if current else None}


def start(db: Session, user: User) -> EchoVoiceTest:
    """Start a test the user asked for: checks every gate, then writes the
    pairs in the background (``ECHO_VOICE_TEST_GENERATION``). A request that
    passed the gates while another was starting a test gets the same
    conflict as one that came second."""
    from app.services import audit_service

    off = offer(db, user)
    if off["blockers"]:
        first = off["blockers"][0]
        raise VoiceTestBlocked(first["code"], first["message"])
    row = EchoVoiceTest(
        tenant_id=user.id, user_id=user.id, status="generating", seed=secrets.randbelow(2**31 - 1),
        pairs_total=PAIRS, model=off["model"],
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        current = latest(db, user.id)
        if current is None or current.status not in OPEN_STATUSES:
            raise
        raise VoiceTestConflict("test_open", _open_message(current)) from None
    db.refresh(row)
    try:
        audit_service.record(db, event="echo_voice_test_started", user_id=user.id, tenant_id=user.id,
                             metadata={"test_id": row.id, "pairs": row.pairs_total})
    except Exception:  # noqa: BLE001
        logger.warning("echo_voice_test_started audit failed", exc_info=True)
    _dispatch(db, user, row.id)
    db.refresh(row)
    return row


def _dispatch(db: Session, user: User, test_id: str) -> str:
    mode = (settings.ECHO_VOICE_TEST_GENERATION or "celery").lower()
    if mode == "off":
        return "off"
    if mode == "inline":
        generate(db, test_id)
        return "ran"
    try:
        from app.services import task_routing_service
        from app.tasks.echo_tasks import generate_voice_test_task

        task_routing_service.dispatch_for_user(generate_voice_test_task, user, test_id)
        return "queued"
    except Exception:  # noqa: BLE001
        logger.exception("voice test: could not queue %s", test_id)
        _fail(db, test_id, "The test could not be started. Try again in a few minutes.")
        return "queue_failed"


def _drafter(db: Session, tenant_id: str) -> Ask:
    """The draft model, as the harness calls its drafter: three tries, the
    text stripped. An empty reply counts as a failed try (a pair with an
    empty side would give the answer away)."""
    from langchain_core.messages import HumanMessage

    from app.services.llm_service import get_llm_for, response_text

    client = get_llm_for(USE_CASE, temperature=DRAFT_TEMPERATURE, max_tokens=DRAFT_MAX_TOKENS, tenant_id=tenant_id, db=db)

    def ask(prompt: str) -> tuple[str, int, int]:
        for attempt in range(3):
            try:
                r = client.invoke([HumanMessage(content=prompt)])
                text = response_text(r).strip()
                if not text:
                    raise ValueError("the model returned nothing")
                usage = getattr(r, "usage_metadata", None) or {}
                return text, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    raise
                logger.warning("voice test: retry after %s: %s", type(e).__name__, e)
                time.sleep(5 * (attempt + 1))
        raise RuntimeError("unreachable")

    return ask


def generate(db: Session, test_id: str, *, ask: Ask | None = None) -> EchoVoiceTest | None:
    """Write the pairs of a test that is ``generating``: hold out
    ``pairs_total`` live notes with the test's seed, build the trait card
    without them, then one topic and one draft call per pair, on the model
    this user's ``echo_draft`` resolves to. Progress is committed pair by
    pair, and a test closed meanwhile stops there and stays closed.
    Fail-soft: any error marks the test failed, in words, and nothing of it
    is shown."""
    from app.services import llm_service, note_service
    from app.services.llm_routing import resolve_config
    from app.services.model_pricing import pricing_for

    row = db.get(EchoVoiceTest, test_id)
    if row is None or row.status != "generating":
        return row
    tenant, seed, pairs_total = row.tenant_id, row.seed, row.pairs_total
    card: HeldOutTraitCard | None = None
    try:
        # The wait in the queue is over: the clock runs from here.
        if not _update_if_generating(db, test_id):
            raise _TestClosed
        notes = list(note_service.iter_notes(db, tenant, include_deleted=False))
        rng = random.Random(seed)
        held = hold_out(notes, rng, pairs_total)
        held_ids = {n.id for n in held}
        held_texts = [(n.id, n.body_md) for n in held]
        remaining = [n.body_md for n in notes if n.id not in held_ids]
        # Nothing of ours may be pending on the database while the what-if
        # holds its own transaction.
        db.commit()
        card = HeldOutTraitCard(db, tenant, [f"note:{i}" for i in held_ids])

        def progress(done: int) -> None:
            if not _update_if_generating(db, test_id, pairs_built=done):
                raise _TestClosed

        with llm_service.byok_context(tenant, db):
            model = resolve_config(USE_CASE).model
            result = build_pairs(held_texts, remaining, ask=ask or _drafter(db, tenant), trait_card=card, rng=rng, on_pair=progress)
        price = pricing_for(model)
        written = _update_if_generating(
            db, test_id, status="ready", ready_at=_now(), model=model,
            pairs_json=json.dumps(result.pairs, ensure_ascii=False),
            key_json=json.dumps(result.keys, ensure_ascii=False),
            tokens_in=result.tokens_in, tokens_out=result.tokens_out,
            cost_usd=round(result.tokens_in / 1e6 * price.input_per_m + result.tokens_out / 1e6 * price.output_per_m, 6) if price else 0.0,
        )
        if not written:
            raise _TestClosed
    except _TestClosed:
        logger.info("voice test: %s was closed while it was being written", test_id)
    except NotEnoughNotes:
        _fail(db, test_id, f"The test needs {MIN_NOTES} of your notes; some were deleted while it was being written.")
    except Exception:  # noqa: BLE001
        logger.exception("voice test: could not write %s", test_id)
        _fail(db, test_id, "Echo could not write the test. Start a new one.")
    finally:
        if card is not None:
            card.close()
    return db.get(EchoVoiceTest, test_id)


def pick(db: Session, tenant_id: str, test_id: str, pair: str, choice: str) -> EchoVoiceTest:
    """Record (or change) the user's pick for one pair."""
    row = get_test(db, tenant_id, test_id)
    if row.status != "ready":
        raise VoiceTestConflict("not_open", "This test is not open for picks.")
    if choice not in ("A", "B"):
        raise ValueError("pick must be A or B")
    if pair not in {p["pair"] for p in json.loads(row.pairs_json or "[]")}:
        raise ValueError(f"no pair {pair} in this test")
    picks = json.loads(row.picks_json or "{}")
    picks[pair] = choice
    row.picks_json = json.dumps(picks)
    db.commit()
    db.refresh(row)
    return row


def score(db: Session, user: User, test_id: str) -> EchoVoiceTest:
    """Score a finished test exactly as ``user-score`` does and store it as
    the user's voice gate exactly as ``--record`` does (a fail is stored too:
    the gate then says so)."""
    from app.services import audit_service, echo_draft_service

    row = get_test(db, user.id, test_id)
    if row.status != "ready":
        raise VoiceTestConflict("not_open", "This test is not open for scoring.")
    keys = json.loads(row.key_json or "[]")
    picks = json.loads(row.picks_json or "{}")
    left = sum(1 for k in keys if picks.get(k["pair"]) not in ("A", "B"))
    if left or not keys:
        raise VoiceTestConflict("incomplete", f"Pick the one you wrote in every pair first: {left} left.")
    result = score_picks(keys, picks)
    row.status = "scored"
    row.picked_own = result["picked_own"]
    row.passed = result["pass"]
    row.scored_at = _now()
    # Commits the test row with the gate.
    gate = echo_draft_service.record_voice_test(db, user.id, pairs=result["pairs"], picked_own=result["picked_own"])
    if (gate.status == "passed") != result["pass"]:  # pragma: no cover - one rule, two places
        logger.error("voice test %s: score and gate disagree", row.id)
    try:
        audit_service.record(db, event="echo_voice_test_scored", user_id=user.id, tenant_id=user.id, metadata={
            "test_id": row.id, "pairs": result["pairs"], "picked_own": result["picked_own"], "passed": result["pass"],
        })
    except Exception:  # noqa: BLE001
        logger.warning("echo_voice_test_scored audit failed", exc_info=True)
    db.refresh(row)
    return row
