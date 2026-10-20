"""Echo signal extraction (S-3.3.2 / E-3.3).

Learns voice and personality signals from the user's OWN words and nothing
else (D-089 item 1):

- live notes (the richest input, D-074; a withdrawn note is withdrawn from
  every signal it fed),
- the questions the user asked on the three Q&A surfaces (not the answers,
  which are the model's words, and not a saved search's scheduled re-asks),
- shares marked as the user's own writing (``voice_eligible``). A
  context-only share never feeds a signal, its annotation included.

Two layers, both batched and both cheap:

1. Stylometry with no model (``echo_stylometry``), per language, recomputed
   from the ledger on every run: ``cadence`` signals.
2. One economy-tier call per batch of inputs (``echo_extract_signals``,
   token-budgeted, reasoning off), emitting style and personality signals
   with verbatim examples. An example is kept only when it is found, exactly,
   in the passage it cites; a signal with no surviving example is dropped.
   Candidates merge into existing rows by ``(signal_type, value_key,
   language)``; the user's rejections are never written again.

``voice_signal_inputs`` records which version of which input was read, so an
edit is re-read (its old evidence withdrawn first) and a deletion is
withdrawn. Every run returns an ``ExtractionReport`` with its token counts
and cost, which is how the costs in the PR were measured.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.models.qa_history_exchange import QAHistoryExchange
from app.models.saved_search_run import SavedSearchRun
from app.models.share import Share
from app.models.voice_signal import VoiceSignal
from app.models.voice_signal_input import VoiceSignalInput
from app.services import echo_signal_service as signals
from app.services import echo_stylometry as stylo

logger = logging.getLogger(__name__)

USE_CASE = "echo_extract_signals"

#: What the LLM layer may emit. ``cadence`` and ``register_per_audience``
#: are left to stylometry and to the user: one batch of text cannot show how
#: tone shifts between audiences.
LLM_TYPES: tuple[str, ...] = tuple(
    t for t in signals.SIGNAL_TYPES if t not in ("cadence", "register_per_audience")
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Inputs


@dataclass(frozen=True)
class Input:
    ref: str
    kind: str
    text: str
    at: str | None
    language: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def language_of(text: str) -> str:
    """en | hi-Deva | hi-Latn | mixed, from the script and the word-level
    Hindi share (``code_mixing_service``, which sees romanised Hindi)."""
    from app.services import code_mixing_service, language_service

    share = code_mixing_service.profile_text(text)["hi_share"]
    script = language_service.dominant_script(text)
    dominant = settings.CODE_MIX_DOMINANT_SHARE
    borrowing = settings.CODE_MIX_BORROWING_MAX_SHARE
    if script == "Devanagari":
        return "hi-Deva" if share >= dominant else "mixed"
    if share >= dominant:
        return "hi-Latn"
    if share <= borrowing:
        return "en"
    return "mixed"


def _iso(dt: datetime | None) -> str | None:
    return dt.date().isoformat() if dt else None


def gather_inputs(db: Session, tenant_id: str) -> list[Input]:
    """Every live input of the tenant, oldest first."""
    from app.services import note_service

    out: list[Input] = []
    for note in note_service.iter_notes(db, tenant_id, include_deleted=False):
        text = (note.body_md or "").strip()
        if text:
            out.append(Input(f"note:{note.id}", "note", text, _iso(note.created_at), language_of(text)))

    rerun_ids = {
        row[0]
        for row in db.query(SavedSearchRun.exchange_id).filter(
            SavedSearchRun.tenant_id == tenant_id, SavedSearchRun.exchange_id.isnot(None)
        )
    }
    for prefix, model in (("qa", QAExchange), ("library_qa", LibraryQAExchange), ("history_qa", QAHistoryExchange)):
        rows = db.query(model.id, model.question, model.created_at).filter(model.tenant_id == tenant_id)
        for ex_id, question, created in rows:
            if ex_id in rerun_ids:
                continue
            text = (question or "").strip()
            if text:
                out.append(Input(f"{prefix}:{ex_id}", "question", text, _iso(created), language_of(text)))

    from app.services.echo_processing_service import voice_eligible

    for share in db.query(Share).filter(Share.tenant_id == tenant_id):
        if not voice_eligible(share):
            continue
        parts = [share.extracted_text or "", share.user_annotation or ""]
        text = "\n\n".join(p.strip() for p in parts if p and p.strip())
        if text:
            out.append(Input(f"share:{share.id}", "share", text, _iso(share.received_at), language_of(text)))

    out.sort(key=lambda i: (i.at or "", i.ref))
    return out


@dataclass
class Pending:
    new: list[Input]
    changed: list[Input]
    gone: list[str]
    #: Unchanged inputs whose LLM pass has not run yet (a failed call).
    retry: list[Input]

    @property
    def to_read(self) -> list[Input]:
        return self.new + self.changed + self.retry

    @property
    def count(self) -> int:
        return len(self.new) + len(self.changed) + len(self.gone) + len(self.retry)


def pending(db: Session, tenant_id: str, inputs: list[Input] | None = None) -> Pending:
    inputs = gather_inputs(db, tenant_id) if inputs is None else inputs
    ledger = {r.source_ref: r for r in db.query(VoiceSignalInput).filter(VoiceSignalInput.tenant_id == tenant_id)}
    live = {i.ref for i in inputs}
    new, changed, retry = [], [], []
    for i in inputs:
        row = ledger.get(i.ref)
        if row is None:
            new.append(i)
        elif row.content_hash != i.content_hash:
            changed.append(i)
        elif not row.llm_done:
            retry.append(i)
    gone = sorted(ref for ref in ledger if ref not in live)
    return Pending(new, changed, gone, retry)


def withdraw_input(db: Session, tenant_id: str, source_ref: str) -> signals.SourceWithdrawal:
    """A deleted or edited input stops counting: out of every signal it fed,
    out of the ledger. Does not commit."""
    result = signals.withdraw_source(db, tenant_id, source_ref)
    db.query(VoiceSignalInput).filter(
        VoiceSignalInput.tenant_id == tenant_id, VoiceSignalInput.source_ref == source_ref
    ).delete(synchronize_session=False)
    return result


# ---------------------------------------------------------------------------
# The LLM layer

EXTRACT_PROMPT = """You are learning how one person thinks and writes, from their own words only. Below are numbered passages THEY wrote: notes, questions they asked, and pieces they marked as their own writing. Each passage says its kind and language.

Find signals of these kinds:
STYLE
- vocabulary: words or phrases they reach for
- framing: how they open, argue or close a point
- recurring_reference: examples, people, events or analogies they return to
- formality_register: how formal they are
PERSONALITY
- trusted_conclusion: something they have settled and build on
- preferred_solution: the kind of fix they reach for first
- recommendation_lens: what they weigh when they recommend something
- apprehension: what makes them wary
- methodology: how they work things out
- topic_emphasis: topics they give the most weight
- perception_lens: the lens they read events through
- interest: what they keep coming back to

Rules:
- "value" is one short sentence IN ENGLISH, whatever language the passages are in, describing the person (e.g. "Distrusts claims that rest on a single source"). Never a summary of a passage.
- Every signal needs at least one example. An example is an EXACT quote copied character for character from one passage, in the passage's own language and script, with that passage's id. Never translate, fix or shorten inside a quote. Quotes are 3 to 40 words.
- Only what the passages show. Prefer signals with examples from two or more passages; a topic mentioned once is not an interest.
- "register": intimate, casual, professional or public when the passages make it clear, otherwise null.
- When one of the known signals below fits, reuse its value word for word instead of rewording it.
- At most {max_signals} signals. If the passages show nothing, return an empty list.

Known signals:
{known}

Passages:
{passages}

Reply with JSON only, no prose:
{{"signals": [{{"signal_type": "interest", "value": "...", "register": null, "examples": [{{"id": "P1", "quote": "..."}}]}}]}}"""


def _tokens(text: str) -> int:
    """About four characters a token; batches only need to be roughly sized."""
    return max(1, len(text) // 4)


def batches(inputs: list[Input], budget: int | None = None, max_inputs: int = 40) -> list[list[Input]]:
    budget = budget or settings.ECHO_SIGNALS_BATCH_TOKENS
    out: list[list[Input]] = []
    cur: list[Input] = []
    used = 0
    for i in inputs:
        cost = min(_tokens(i.text), budget)
        if cur and (used + cost > budget or len(cur) >= max_inputs):
            out.append(cur)
            cur, used = [], 0
        cur.append(i)
        used += cost
    if cur:
        out.append(cur)
    return out


def _passage_text(i: Input, budget_chars: int) -> str:
    return i.text if len(i.text) <= budget_chars else i.text[:budget_chars]


def build_prompt(batch: list[Input], known: list[tuple[str, str]]) -> tuple[str, dict[str, Input]]:
    ids: dict[str, Input] = {}
    lines = []
    per_passage = settings.ECHO_SIGNALS_BATCH_TOKENS * 4
    for n, i in enumerate(batch, start=1):
        pid = f"P{n}"
        ids[pid] = i
        lines.append(f"[{pid}] ({i.kind}, {i.language})\n{_passage_text(i, per_passage)}")
    known_lines = "\n".join(f"- {t}: {v}" for t, v in known[:80]) or "(none yet)"
    prompt = EXTRACT_PROMPT.format(
        max_signals=settings.ECHO_SIGNALS_MAX_PER_BATCH,
        known=known_lines,
        passages="\n\n".join(lines),
    )
    return prompt, ids


_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", " ": " "})


def _normalise_with_map(text: str) -> tuple[str, list[int]]:
    out: list[str] = []
    index: list[int] = []
    prev_space = True
    for pos, ch in enumerate(text.translate(_QUOTES)):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            index.append(pos)
            prev_space = True
        else:
            out.append(ch.casefold())
            index.append(pos)
            prev_space = False
    return "".join(out), index


def find_verbatim(quote: str, text: str) -> str | None:
    """The span of ``text`` the quote copies, ignoring case, spacing and
    curly-versus-straight quote marks; ``None`` when it is not there."""
    q, _ = _normalise_with_map(quote.strip().strip("\"'“”"))
    if len(q) < 8:
        return None
    norm, index = _normalise_with_map(text)
    at = norm.find(q)
    if at < 0:
        return None
    return text[index[at] : index[at + len(q) - 1] + 1]


def _signal_language(signal_type: str, example_languages: list[str]) -> str | None:
    """A style signal belongs to the language its examples are in (the
    majority of their passages, as ``language_of`` read them, never the
    model's label, which drifts between runs on Hinglish). A personality
    signal is what the person thinks, whatever language they say it in, so
    it has none: otherwise one belief splits into a row per language."""
    if signal_type not in signals.STYLE_TYPES or not example_languages:
        return None
    counts: dict[str, int] = {}
    for lang in example_languages:
        counts[lang] = counts.get(lang, 0) + 1
    return max(counts, key=lambda k: (counts[k], -example_languages.index(k)))


def parse_reply(raw: str, ids: dict[str, Input]) -> tuple[list[dict], int]:
    """Valid candidates and the count of examples dropped for not being
    found in their passage."""
    body = raw.strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("reply is not JSON")
    data = json.loads(body[start : end + 1])
    items = data.get("signals") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("reply has no signals list")
    out: list[dict] = []
    dropped = 0
    for item in items[: settings.ECHO_SIGNALS_MAX_PER_BATCH]:
        if not isinstance(item, dict):
            continue
        signal_type = item.get("signal_type")
        value = item.get("value")
        if signal_type not in LLM_TYPES or not isinstance(value, str) or not value.strip():
            continue
        examples = []
        for ex in item.get("examples") or []:
            if not isinstance(ex, dict):
                continue
            src = ids.get(str(ex.get("id", "")).strip())
            span = find_verbatim(str(ex.get("quote", "")), src.text) if src else None
            if span is None:
                dropped += 1
                continue
            examples.append({"text": span, "source": src.ref, **({"at": src.at} if src.at else {}), "_language": src.language})
        if not examples:
            continue
        language = _signal_language(signal_type, [e["_language"] for e in examples])
        register = item.get("register") if item.get("register") in signals.REGISTERS else None
        out.append({
            "signal_type": signal_type,
            "value": " ".join(value.split())[: signals.MAX_VALUE_CHARS],
            "language": language,
            "register": register,
            "examples": [{k: v for k, v in e.items() if not k.startswith("_")} for e in examples],
        })
    return out, dropped


# ---------------------------------------------------------------------------
# Merging


@dataclass
class MergeCounts:
    created: int = 0
    merged: int = 0
    revived: int = 0
    rejected_by_user: int = 0


def _key_rows(db: Session, tenant_id: str, signal_type: str, value: str, language: str | None) -> list[VoiceSignal]:
    q = db.query(VoiceSignal).filter(
        VoiceSignal.tenant_id == tenant_id,
        VoiceSignal.signal_type == signal_type,
        VoiceSignal.value_key == signals.value_key(value),
    )
    q = q.filter(VoiceSignal.language.is_(None)) if language is None else q.filter(VoiceSignal.language == language)
    return q.all()


def _add_examples(row: VoiceSignal, examples: list[dict]) -> int:
    """Add evidence; returns the number of NEW sources (the weight added)."""
    have = json.loads(row.examples_json or "[]")
    sources = json.loads(row.derived_from or "[]")
    new_sources = 0
    for ex in examples:
        if ex["source"] not in sources:
            sources.append(ex["source"])
            new_sources += 1
        if all(h.get("text") != ex["text"] for h in have):
            have.append(ex)
    # Most recent first, one per source before a second from the same source.
    have.sort(key=lambda e: e.get("at") or "", reverse=True)
    seen: set[str] = set()
    first = [e for e in have if not (e["source"] in seen or seen.add(e["source"]))]
    rest = [e for e in have if e not in first]
    row.examples_json = json.dumps((first + rest)[: signals.MAX_EXAMPLES], ensure_ascii=False)
    row.derived_from = json.dumps(sources)
    return new_sources


def merge_candidate(db: Session, tenant_id: str, cand: dict, origin: str, counts: MergeCounts) -> VoiceSignal | None:
    rows = _key_rows(db, tenant_id, cand["signal_type"], cand["value"], cand["language"])
    if any(r.suppressed_reason == "user" for r in rows):
        counts.rejected_by_user += 1
        return None
    live = next((r for r in rows if r.suppressed_at is None), None)
    if live is not None:
        live.weight = float(live.weight) + _add_examples(live, cand["examples"])
        if cand.get("register") and not live.register:
            live.register = cand["register"]
        counts.merged += 1
        return live
    revivable = next((r for r in rows if r.suppressed_reason == "source_deleted"), None)
    if revivable is not None:
        revivable.suppressed_at = None
        revivable.suppressed_reason = None
        revivable.examples_json = "[]"
        revivable.derived_from = "[]"
        revivable.weight = float(_add_examples(revivable, cand["examples"]))
        revivable.consent_version = signals.CONSENT_VERSION
        counts.revived += 1
        return revivable
    row = VoiceSignal(
        tenant_id=tenant_id,
        user_id=tenant_id,
        signal_type=cand["signal_type"],
        value=cand["value"],
        value_key=signals.value_key(cand["value"]),
        weight=0.0,
        examples_json="[]",
        derived_from="[]",
        language=cand["language"],
        register=cand.get("register"),
        origin=origin,
        consent_version=signals.CONSENT_VERSION,
    )
    row.weight = float(_add_examples(row, cand["examples"]))
    db.add(row)
    db.flush()
    counts.created += 1
    return row


def _record_on_shares(db: Session, tenant_id: str, row: VoiceSignal) -> None:
    """A share lists the signals it fed, so deleting it can withdraw them."""
    for ref in json.loads(row.derived_from or "[]"):
        if not ref.startswith("share:"):
            continue
        share = db.get(Share, ref.split(":", 1)[1])
        if share is None or share.tenant_id != tenant_id:
            continue
        ids = json.loads(share.derived_signal_ids_json or "[]")
        if row.id not in ids:
            share.derived_signal_ids_json = json.dumps(ids + [row.id])


# ---------------------------------------------------------------------------
# Stylometry layer


def sync_stylometry(db: Session, tenant_id: str, inputs: dict[str, Input], counts: MergeCounts) -> int:
    """Recompute ``cadence`` signals per language from the ledger. A cadence
    the text no longer shows is removed (it was never the user's own words or
    a rejection); the user's rejections are respected."""
    by_lang: dict[str, list[VoiceSignalInput]] = {}
    for row in db.query(VoiceSignalInput).filter(VoiceSignalInput.tenant_id == tenant_id):
        # Prose only: a question typed into Q&A is always a question, and
        # counting it would make everyone "ask questions often".
        if row.language and row.kind != "question":
            by_lang.setdefault(row.language, []).append(row)
    kept_ids: set[str] = set()
    for language, rows in by_lang.items():
        prof = stylo.combine(stylo.StyleProfile.from_json(json.loads(r.features_json or "{}")) for r in rows)
        found = stylo.cadence_signals(prof)
        recent = sorted((inputs[r.source_ref] for r in rows if r.source_ref in inputs), key=lambda i: i.at or "", reverse=True)
        mean = prof.mean_sentence_words
        for sig in found:
            examples = []
            for i in recent:
                for s in stylo.raw_sentences(i.text):
                    if stylo.exhibits(stylo.plain(s), sig.habit, mean):
                        examples.append({"text": s[: signals.MAX_EXAMPLE_CHARS], "source": i.ref, **({"at": i.at} if i.at else {})})
                        break
                if len(examples) >= 3:
                    break
            if not examples:
                continue
            row = merge_candidate(
                db, tenant_id,
                {"signal_type": "cadence", "value": sig.value, "language": language, "register": None, "examples": examples},
                "stylometry", counts,
            )
            if row is not None:
                kept_ids.add(row.id)
    stale = [
        r
        for r in db.query(VoiceSignal).filter(
            VoiceSignal.tenant_id == tenant_id,
            VoiceSignal.origin == "stylometry",
            VoiceSignal.suppressed_at.is_(None),
        )
        if r.id not in kept_ids
    ]
    for r in stale:
        db.delete(r)
    return len(stale)


# ---------------------------------------------------------------------------
# A run


@dataclass
class ExtractionReport:
    inputs_read: int = 0
    withdrawn: int = 0
    batches: int = 0
    calls_failed: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    examples_dropped: int = 0
    stylometry_removed: int = 0
    model: str | None = None
    counts: MergeCounts = field(default_factory=MergeCounts)

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "counts"}
        d.update(self.counts.__dict__)
        return d


LLMCall = Callable[[str], tuple[str, int, int]]


def _default_llm(tenant_id: str, db: Session) -> tuple[LLMCall, str]:
    from langchain_core.messages import HumanMessage

    from app.services.llm_routing import resolve_config
    from app.services.llm_service import get_llm_for, response_text

    model = resolve_config(USE_CASE).model
    client = get_llm_for(USE_CASE, temperature=0.0, max_tokens=settings.ECHO_SIGNALS_MAX_OUTPUT_TOKENS, tenant_id=tenant_id, db=db)

    def call(prompt: str) -> tuple[str, int, int]:
        response = client.invoke([HumanMessage(content=prompt)])
        usage = getattr(response, "usage_metadata", None) or {}
        return response_text(response), int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)

    return call, model


def _cost(model: str | None, tokens_in: int, tokens_out: int) -> float:
    from app.services.model_pricing import pricing_for

    price = pricing_for(model or "")
    if price is None:
        return 0.0
    return round(tokens_in / 1e6 * price.input_per_m + tokens_out / 1e6 * price.output_per_m, 6)


def run(db: Session, tenant_id: str, *, llm: LLMCall | None = None, model: str | None = None, use_llm: bool = True) -> ExtractionReport:
    """One extraction run for a tenant. Commits."""
    report = ExtractionReport()
    inputs = gather_inputs(db, tenant_id)
    state = pending(db, tenant_id, inputs)
    by_ref = {i.ref: i for i in inputs}

    for ref in state.gone:
        withdraw_input(db, tenant_id, ref)
        report.withdrawn += 1
    for i in state.changed:
        withdraw_input(db, tenant_id, i.ref)
        report.withdrawn += 1
    db.flush()

    # Ledger rows first: stylometry needs them whether or not the LLM runs.
    ledger: dict[str, VoiceSignalInput] = {
        r.source_ref: r for r in db.query(VoiceSignalInput).filter(VoiceSignalInput.tenant_id == tenant_id)
    }
    for i in state.new + state.changed:
        row = VoiceSignalInput(
            tenant_id=tenant_id,
            source_ref=i.ref,
            kind=i.kind,
            content_hash=i.content_hash,
            language=i.language,
            llm_done=False,
            features_json=json.dumps(stylo.profile(i.text).to_json(), ensure_ascii=False),
        )
        db.add(row)
        ledger[i.ref] = row
    db.flush()
    report.inputs_read = len(state.to_read)

    to_read = state.to_read
    if use_llm and to_read:
        if llm is None:
            llm, model = _default_llm(tenant_id, db)
        report.model = model
        known = [
            (r.signal_type, r.value)
            for r in signals.list_signals(db, tenant_id)
            if r.signal_type in LLM_TYPES
        ]
        for batch in batches(to_read)[: settings.ECHO_SIGNALS_MAX_BATCHES_PER_RUN]:
            prompt, ids = build_prompt(batch, known)
            try:
                raw, t_in, t_out = llm(prompt)
                report.tokens_in += t_in or _tokens(prompt)
                report.tokens_out += t_out or _tokens(raw)
                candidates, dropped = parse_reply(raw, ids)
            except Exception as e:  # noqa: BLE001 — fail-soft: the batch stays pending
                logger.warning("echo signals: batch of %d failed for tenant %s: %s", len(batch), tenant_id[:8], e)
                report.calls_failed += 1
                report.batches += 1
                continue
            report.batches += 1
            report.examples_dropped += dropped
            for cand in candidates:
                row = merge_candidate(db, tenant_id, cand, "llm", report.counts)
                if row is not None:
                    _record_on_shares(db, tenant_id, row)
                    if (row.signal_type, row.value) not in known:
                        known.append((row.signal_type, row.value))
            for i in batch:
                ledger[i.ref].llm_done = True
                ledger[i.ref].processed_at = _now()
        report.cost_usd = _cost(report.model, report.tokens_in, report.tokens_out)

    report.stylometry_removed = sync_stylometry(db, tenant_id, by_ref, report.counts)
    db.commit()
    # S-3.3.3: the retrieval collection follows the rows.
    from app.services import echo_personal_vectors

    echo_personal_vectors.sync_soft(db, tenant_id)
    logger.info("echo signals: tenant %s run %s", tenant_id[:8], report.to_dict())
    return report


# ---------------------------------------------------------------------------
# Queueing


def maybe_queue(db: Session, tenant_id: str, *, force: bool = False) -> str:
    """Queue a run when enough new input has arrived (``ECHO_SIGNALS_MIN_NEW_INPUTS``)
    or when ``force`` and anything is pending. Fail-soft: returns what
    happened and never raises into the caller's request."""
    try:
        mode = (settings.ECHO_SIGNAL_EXTRACTION or "off").lower()
        if mode == "off":
            return "off"
        from app.models.user import User
        from app.services.tier_service import has_feature

        user = db.get(User, tenant_id)
        if user is None or not has_feature(user, "echo_personal_brain"):
            return "not_entitled"
        state = pending(db, tenant_id)
        if state.count == 0 or (not force and state.count < settings.ECHO_SIGNALS_MIN_NEW_INPUTS):
            return "waiting"
        if mode == "inline":
            run(db, tenant_id)
            return "ran"
        from app.services import task_routing_service
        from app.tasks.echo_tasks import extract_signals_task

        task_routing_service.dispatch_for_user(extract_signals_task, user, tenant_id)
        return "queued"
    except Exception:  # noqa: BLE001
        logger.exception("echo signals: could not queue extraction for tenant %s", tenant_id[:8])
        return "queue_failed"


def last_learned_at(db: Session, tenant_id: str) -> datetime | None:
    from sqlalchemy import func

    return (
        db.query(func.max(VoiceSignalInput.processed_at))
        .filter(VoiceSignalInput.tenant_id == tenant_id, VoiceSignalInput.llm_done.is_(True))
        .scalar()
    )


def inputs_by_language(inputs: Iterable[Input]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in inputs:
        out[i.language] = out.get(i.language, 0) + 1
    return out
