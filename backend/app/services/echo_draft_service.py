""""Speak as me" (S-3.4.1): the gates, the real retrievers, persistence.

The agent is ``app.agents.echo_agent``; this module decides whether it may
run and gives it the user's material. Gates, in order (``status``):

1. ``install_off``: ``ECHO_SPEAK_AS_ME_ENABLED`` is off (the default).
2. ``not_ready``: ``echo_service.is_ready`` (the readiness gate, D-049).
3. ``voice_test_required`` / ``voice_test_failed``: the per-user switch D-100
   requires. A user passes the blinded "which of these did you write?"
   test (tier iii: at least 20 pairs, own text picked in at most 80%) with
   ``scripts/voice_match_harness.py user-pairs`` / ``user-score --record``.
4. ``daily_cap``: ``echo_drafts`` per day through ``quota_metering_service``.

The tier feature (``echo_speak_as_me``) is the router's 403, before any of
this. A draft is never sent; it is stored in ``echo_drafts`` (part of the
brain, D-089) with what grounded it.

**Provenance guard, in code.** Exemplars come from the user's live notes
and their own-words shares (``voice_eligible``) only; trait cards are their
signals, which are learned from their own words only (S-3.3.2). Nothing
written by anyone else can set the voice, which makes speaking as someone
else structurally impossible.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.echo_draft import EchoDraft, EchoVoiceGate
from app.models.user import User

logger = logging.getLogger(__name__)

QUOTA_RESOURCE = "echo_drafts"
#: Pre-registered tier (iii) rule, docs/notes/2026-10-19-voice-match-preregistration.md.
VOICE_TEST_MIN_PAIRS = 20
VOICE_TEST_MAX_OWN_SHARE = 0.80
VOICE_TEST_RULE_VERSION = "2026-10-19"


class DraftBlocked(Exception):
    def __init__(self, code: str, message: str, status: "DraftStatus"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class NamesNeedConfirmation(Exception):
    def __init__(self, names: list[str]):
        super().__init__(", ".join(names))
        self.names = names


class DraftCapReached(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class DraftNotFound(LookupError):
    pass


@dataclass
class DraftStatus:
    enabled: bool
    blockers: list[dict]
    readiness: dict
    voice_gate: dict
    drafts_today: int
    drafts_per_day: int

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# The voice gate (tier iii)


def voice_gate(db: Session, tenant_id: str) -> dict:
    from app.services import note_service

    row = db.query(EchoVoiceGate).filter(EchoVoiceGate.tenant_id == tenant_id).first()
    notes = note_service.voice_stats(db, tenant_id).notes_total
    return {
        "status": row.status if row else "not_run",
        "run_at": row.run_at.isoformat() + "Z" if row else None,
        "pairs": row.pairs if row else 0,
        "picked_own_share": row.picked_own_share if row else None,
        "notes_total": notes,
        "notes_needed": settings.ECHO_VOICE_TEST_MIN_NOTES,
    }


def record_voice_test(db: Session, tenant_id: str, *, pairs: int, picked_own: int) -> EchoVoiceGate:
    """Apply the pre-registered rule to a finished test and store the result
    (replacing an earlier one). Called by the harness's ``user-score --record``."""
    if pairs <= 0 or not 0 <= picked_own <= pairs:
        raise ValueError("pairs must be positive and picked_own between 0 and pairs")
    share = picked_own / pairs
    passed = pairs >= VOICE_TEST_MIN_PAIRS and share <= VOICE_TEST_MAX_OWN_SHARE
    row = db.query(EchoVoiceGate).filter(EchoVoiceGate.tenant_id == tenant_id).first()
    if row is None:
        row = EchoVoiceGate(tenant_id=tenant_id, status="", pairs=0, picked_own_share=0.0, rule_version=VOICE_TEST_RULE_VERSION)
        db.add(row)
    row.status = "passed" if passed else "failed"
    row.pairs = pairs
    row.picked_own_share = round(share, 4)
    row.rule_version = VOICE_TEST_RULE_VERSION
    row.run_at = _now()
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Status


def _cap(user: User) -> int:
    from app.services import quota_metering_service

    return quota_metering_service._resolve_limit(user, QUOTA_RESOURCE)  # noqa: SLF001


def drafts_today(db: Session, user: User) -> int:
    from app.services import quota_metering_service

    return quota_metering_service.get_usage(db, user.id, QUOTA_RESOURCE)


def status(db: Session, user: User) -> DraftStatus:
    from app.services import echo_service

    readiness = asdict(echo_service.is_ready(db, user.id))
    gate = voice_gate(db, user.id)
    used, cap = drafts_today(db, user), _cap(user)
    blockers: list[dict] = []
    if not settings.ECHO_SPEAK_AS_ME_ENABLED:
        blockers.append({"code": "install_off", "message": "Speak as me is turned off on this install."})
    if not readiness["ready"]:
        missing = [f"{readiness['total_rows']} of {readiness['threshold_total']} facts",
                   f"{readiness['distinct_sources']} of {readiness['threshold_sources']} sources"]
        if not readiness["has_personality_trait"]:
            missing.append("a personality trait")
        blockers.append({"code": "not_ready", "message": "Echo needs more to go on first: " + ", ".join(missing) + "."})
    if gate["status"] == "not_run":
        blockers.append({
            "code": "voice_test_required",
            "message": (
                "Speak as me turns on after you pass the “which of these did you write?” test, which checks that "
                f"Echo's drafts can pass for your writing. It needs {gate['notes_needed']} of your notes; "
                f"you have {gate['notes_total']}."
            ),
        })
    elif gate["status"] == "failed":
        blockers.append({
            "code": "voice_test_failed",
            "message": (
                f"In your last test you picked your own writing in {round(100 * gate['picked_own_share'])}% of "
                f"{gate['pairs']} pairs; it passes at {round(100 * VOICE_TEST_MAX_OWN_SHARE)}% or less over at least "
                f"{VOICE_TEST_MIN_PAIRS}. Write more, then take it again."
            ),
        })
    if cap >= 0 and used >= cap:
        blockers.append({"code": "daily_cap", "message": f"You have used today's {cap} drafts. More tomorrow."})
    return DraftStatus(
        enabled=not blockers, blockers=blockers, readiness=readiness, voice_gate=gate,
        drafts_today=used, drafts_per_day=cap,
    )


# ---------------------------------------------------------------------------
# The real dependencies


def _llm(use_case: str, tenant_id: str, db: Session, max_tokens: int):
    from langchain_core.messages import HumanMessage

    from app.services.llm_service import get_llm_for, response_text

    client = get_llm_for(use_case, temperature=1.0, max_tokens=max_tokens, tenant_id=tenant_id, db=db)

    def call(prompt: str) -> tuple[str, int, int]:
        r = client.invoke([HumanMessage(content=prompt)])
        usage = getattr(r, "usage_metadata", None) or {}
        return response_text(r), int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)

    return call


def own_texts(db: Session, tenant_id: str) -> list[str]:
    """The user's own words that may set the voice: live notes and shares
    marked as written by them. Nothing else, ever (the provenance guard)."""
    from app.models.share import Share
    from app.services import note_service
    from app.services.echo_processing_service import voice_eligible

    out = [n.body_md for n in note_service.iter_notes(db, tenant_id, include_deleted=False) if (n.body_md or "").strip()]
    for share in db.query(Share).filter(Share.tenant_id == tenant_id, Share.author_is_tenant.is_(True)):
        if voice_eligible(share) and (share.extracted_text or "").strip():
            out.append(share.extracted_text)
    return out


def exemplars(texts: list[str], language: str, language_of, k: int = 5) -> list[str]:
    """Style diversity within the target language, not topic (D-100's
    harness): spread over the sentence-length range. Falls back to every
    language when the target has fewer than ``k``."""
    from app.services import echo_stylometry as stylo

    short = [t[:1200] for t in texts]
    pool = [t for t in short if language_of(t) == language]
    if len(pool) < k:
        pool = short
    ranked = sorted(pool, key=lambda t: stylo.profile(t).mean_sentence_words)
    if len(ranked) <= k:
        return ranked
    idx = sorted({round(i * (len(ranked) - 1) / (k - 1)) for i in range(k)})
    return [ranked[i] for i in idx]


def _real_deps(db: Session, user: User):
    from app.agents.echo_agent import ContextItem, DraftDeps
    from app.models.voice_signal import VoiceSignal
    from app.services import chroma_service, echo_personal_vectors, echo_vectors, note_index, qa_scope_service
    from app.services import echo_signal_extraction as extraction
    from app.services.llm_routing import resolve_config

    tenant = user.id

    def knowledge(topic: str) -> list[ContextItem]:
        items: list[ContextItem] = []
        doc_ids = qa_scope_service.resolve_document_ids(db, tenant, None)
        for n, hit in enumerate(chroma_service.query_collection(topic, n_results=settings.ECHO_DRAFT_SOURCES, document_ids=doc_ids), 1):
            md = hit.get("metadata") or {}
            url = md.get("video_url") or md.get("source_url") or None
            if url and md.get("timestamp_start") is not None and "youtube" in url:
                url = f"{url}{'&' if '?' in url else '?'}t={int(float(md['timestamp_start']))}s"
            label = " — ".join(x for x in (md.get("video_title") or md.get("title"), md.get("channel_name")) if x) or "a source"
            items.append(ContextItem(f"S{n}", "source", hit["text"][:1500], label, url, third_party=True))
        for n, hit in enumerate(note_index.query_notes(topic, tenant, n_results=4), 1):
            items.append(ContextItem(f"N{n}", "note", hit["text"][:1200], "your note", None, third_party=False))
        for n, hit in enumerate(echo_vectors.query_share_vectors(tenant, topic, n=3), 1):
            md = hit.get("metadata") or {}
            # A context-only share may ground the draft but is never quoted
            # (D-089 item 1); the user's own share is their own words.
            own = bool(md.get("author_is_tenant"))
            items.append(ContextItem(f"S{len(items) + 1}", "share", hit["text"][:1200],
                                     "something you wrote and shared" if own else "something you shared",
                                     None, third_party=not own))
        for n, hit in enumerate(chroma_service.query_qa_collection(topic, top_k=3, tenant_id=tenant), 1):
            # A past answer is the model's words over third-party sources.
            items.append(ContextItem(f"Q{n}", "qa", hit["text"][:1200], "a question you asked before", None, third_party=True))
        return items

    def facts(topic: str) -> list[ContextItem]:
        return [
            ContextItem(f"F{n}", "fact", h.text[:600], "what Echo knows about you", None, third_party=False)
            for n, h in enumerate(echo_personal_vectors.query_personal_context(tenant, topic, n=6, kinds=["fact"]), 1)
        ]

    def signals(topic: str, language: str) -> list[str]:
        lines = [h.text.split("\nExamples:")[0] for h in echo_personal_vectors.query_personal_context(tenant, topic, n=8, kinds=["signal"])]
        for c in db.query(VoiceSignal).filter(
            VoiceSignal.tenant_id == tenant, VoiceSignal.signal_type == "cadence",
            VoiceSignal.suppressed_at.is_(None), VoiceSignal.language == language,
        ):
            line = f"style · cadence: {c.value}"
            if line not in lines:
                lines.append(line)
        return lines

    texts = own_texts(db, tenant)
    return DraftDeps(
        classify=_llm("echo_classify_intent", tenant, db, 600),
        draft=_llm("echo_draft", tenant, db, 1500),
        critique=_llm("echo_critique", tenant, db, 900),
        knowledge=knowledge,
        signals=signals,
        facts=facts,
        exemplars=lambda language: exemplars(texts, language, extraction.language_of),
        language_of=extraction.language_of,
        models={u: resolve_config(u).model for u in ("echo_classify_intent", "echo_draft", "echo_critique")},
    )


# ---------------------------------------------------------------------------
# Draft


def disclosure_for(user: User) -> str:
    name = (getattr(user, "display_name", None) or user.email.split("@")[0]).strip()
    return f"Drafted with Echo, reviewed by {name}"


def draft(
    db: Session,
    user: User,
    message: str,
    *,
    audience: str | None = None,
    register: str | None = None,
    language: str | None = None,
    acknowledge_names: list[str] | tuple[str, ...] = (),
    deps: Any = None,
) -> EchoDraft:
    """One draft. Raises ``DraftBlocked``, ``DraftCapReached`` or
    ``NamesNeedConfirmation``; spends nothing when it raises before the model."""
    from app.agents.echo_agent import run_echo_draft
    from app.services import audit_service, quota_metering_service

    st = status(db, user)
    gate = [b for b in st.blockers if b["code"] != "daily_cap"]
    if gate:
        raise DraftBlocked(gate[0]["code"], gate[0]["message"], st)
    if any(b["code"] == "daily_cap" for b in st.blockers):
        raise DraftCapReached(next(b["message"] for b in st.blockers if b["code"] == "daily_cap"))

    deps = deps or _real_deps(db, user)
    state = run_echo_draft(
        deps, message=message, audience=audience, register=register, language=language,
        acknowledge_names=list(acknowledge_names),
    )
    if state.get("needs_confirmation"):
        raise NamesNeedConfirmation(state["needs_confirmation"])
    result = state["result"]
    model = deps.models.get("echo_draft") if getattr(deps, "models", None) else None
    from app.services.model_pricing import pricing_for

    price = pricing_for(model or "")
    cost = (state.get("tokens_in", 0) / 1e6 * price.input_per_m + state.get("tokens_out", 0) / 1e6 * price.output_per_m) if price else 0.0
    row = EchoDraft(
        tenant_id=user.id, user_id=user.id, input_message=message, audience=audience, register=register,
        language=state["language"], intent=state.get("intent"), draft=result["draft"],
        voice_match_score=result["voice_match_score"], confidence=result["confidence"],
        citations_json=json.dumps(result["citations"], ensure_ascii=False),
        deviation_notes_json=json.dumps(result["deviation_notes"], ensure_ascii=False),
        flags_json=json.dumps(result["flags"]), critique_rounds=result["critique_rounds"], model=model,
        tokens_in=state.get("tokens_in", 0), tokens_out=state.get("tokens_out", 0), cost_usd=round(cost, 6),
        disclosure=disclosure_for(user),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    quota_metering_service.record_usage(db, user.id, QUOTA_RESOURCE)
    try:
        audit_service.record(db, event="echo_drafted", user_id=user.id, tenant_id=user.id, metadata={
            "draft_id": row.id, "language": row.language, "intent": row.intent, "citations": len(result["citations"]),
            "voice_match_score": row.voice_match_score, "flags": result["flags"],
        })
    except Exception:  # noqa: BLE001
        logger.exception("echo draft: audit failed for %s", row.id)
    return row


def to_dict(row: EchoDraft) -> dict:
    return {
        "id": row.id,
        "message": row.input_message,
        "draft": row.draft,
        "language": row.language,
        "register": row.register,
        "audience": row.audience,
        "intent": row.intent,
        "voice_match_score": row.voice_match_score,
        "confidence": row.confidence,
        "citations": json.loads(row.citations_json or "[]"),
        "deviation_notes": json.loads(row.deviation_notes_json or "[]"),
        "flags": json.loads(row.flags_json or "[]"),
        "disclosure": row.disclosure,
        "final_text": row.final_text,
        "disclosure_kept": row.disclosure_kept,
        "created_at": row.created_at,
    }


def list_drafts(db: Session, tenant_id: str, limit: int = 20) -> list[EchoDraft]:
    return (
        db.query(EchoDraft).filter(EchoDraft.tenant_id == tenant_id)
        .order_by(EchoDraft.created_at.desc(), EchoDraft.id.desc()).limit(max(1, min(limit, 100))).all()
    )


def get_draft(db: Session, tenant_id: str, draft_id: str) -> EchoDraft:
    row = db.get(EchoDraft, draft_id)
    if row is None or row.tenant_id != tenant_id:
        raise DraftNotFound(draft_id)
    return row


def delete_draft(db: Session, tenant_id: str, draft_id: str) -> None:
    db.delete(get_draft(db, tenant_id, draft_id))
    db.commit()
