""""Speak as me" (S-3.4.1 / E-3.4): draft a reply in the user's voice.

    classify_intent -> [names need confirmation? stop]
      -> retrieve_relevant_knowledge -> retrieve_voice_signals
      -> retrieve_personal_context -> draft -> self_critique_against_voice
      -> (revise -> self_critique, up to ECHO_DRAFT_CRITIQUE_ROUNDS; keep the best)
      -> finalize

Mode A, as D-100's gate ran it: the user's signals as a trait card plus five
of their own texts chosen for style diversity, no fine-tuning. The model
calls and the retrievers arrive in ``DraftDeps`` so tests can patch every one;
``app.services.echo_draft_service`` builds the real ones and owns the gates
(install switch, readiness, the per-user voice test, the daily cap).

What code guarantees, not the prompt:

- **Third-party words are never quoted.** Any run of ``VERBATIM_WORDS``
  words shared with a third-party passage (a library source, a context-only
  share, a past answer) is paraphrased once, and if it survives, the
  sentence holding it is removed (D-089 item 1).
- **Only the user's own texts set the voice.** Exemplars come from the
  ``exemplars`` dep, which the service fills from notes and own-words shares
  only; signals are learned from own words only (S-3.3.2).
- **Private people are confirmed before drafting.** A message that names a
  person the classifier calls private stops with the names unless the caller
  acknowledged them.
- **Citations are what the draft used.** Markers the draft cites are mapped
  to the items it was given; markers that match nothing are dropped. The
  delivered text carries no markers.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.prompts.echo_draft_prompts import (
    CLASSIFY_PROMPT,
    CRITIQUE_PROMPT,
    DRAFT_PROMPT,
    PARAPHRASE_PROMPT,
    REVISE_PROMPT,
)
from app.config import settings
from app.services import echo_stylometry as stylo

logger = logging.getLogger(__name__)

#: A run of this many words shared with a third-party passage is a quote.
VERBATIM_WORDS = 8

LANGUAGE_NAMES = {
    "en": "English",
    "hi-Deva": "Hindi written in Devanagari",
    "hi-Latn": "Hindi written in Roman letters, the way they write it",
    "mixed": "the mix of Hindi and English they use",
}
INTENTS = ("question", "opinion", "recommendation", "request", "social", "other")
LLMCall = Callable[[str], tuple[str, int, int]]


@dataclass(frozen=True)
class ContextItem:
    """Something a draft may draw on. ``marker`` (S1, F2, N1, Q3) is how the
    draft cites it; ``third_party`` items are never quoted."""

    marker: str
    kind: str  # source | share | note | qa | fact
    text: str
    label: str
    url: str | None = None
    third_party: bool = True


@dataclass
class DraftDeps:
    classify: LLMCall
    draft: LLMCall
    critique: LLMCall
    #: topic -> library sources, own notes, past Q&As, shares (S#, N#, Q#)
    knowledge: Callable[[str], list[ContextItem]]
    #: (topic, language) -> trait-card lines
    signals: Callable[[str, str], list[str]]
    #: topic -> facts about the user (F#)
    facts: Callable[[str], list[ContextItem]]
    #: language -> up to five of the user's own texts, style-diverse
    exemplars: Callable[[str], list[str]]
    #: text -> en | hi-Deva | hi-Latn | mixed
    language_of: Callable[[str], str]
    models: dict[str, str] = field(default_factory=dict)


class DraftState(TypedDict, total=False):
    message: str
    audience: str | None
    register: str | None
    language: str | None
    acknowledge_names: list[str]
    intent: str
    topic: str
    people: list[dict]
    needs_confirmation: list[str]
    knowledge: list[ContextItem]
    facts: list[ContextItem]
    trait_card: list[str]
    exemplars: list[str]
    draft_prompt: str
    candidates: list[dict]
    rounds: int
    tokens_in: int
    tokens_out: int
    result: dict


def _json(raw: str) -> dict:
    body = raw.strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    data = json.loads(body[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("reply is not an object")
    return data


def _numbered(items: list[ContextItem]) -> str:
    return "\n\n".join(f"[{i.marker}] ({i.kind}: {i.label})\n{i.text}" for i in items) or "(nothing relevant)"


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) or "- (nothing learned yet)"


# ---------------------------------------------------------------------------
# Guards


_MARKER = re.compile(r"\s*\[((?:[SFNQ]\d+)(?:\s*,\s*[SFNQ]\d+)*)\]")


def cited_markers(text: str) -> list[str]:
    out: list[str] = []
    for m in _MARKER.finditer(text):
        for marker in re.split(r"\s*,\s*", m.group(1)):
            if marker not in out:
                out.append(marker)
    return out


def strip_markers(text: str) -> str:
    clean = _MARKER.sub("", text)
    clean = re.sub(r"\s+([.,;:!?।])", r"\1", clean)
    return re.sub(r"[ \t]{2,}", " ", clean).strip()


def _ngrams(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def verbatim_spans(draft: str, passages: list[str], n: int = VERBATIM_WORDS) -> list[str]:
    """Runs of ``n`` words the draft shares with any passage, as the draft's
    words (joined), longest first."""
    words = stylo.words(strip_markers(draft))
    theirs: set[tuple[str, ...]] = set()
    for p in passages:
        theirs |= _ngrams(stylo.words(p), n)
    hits = [i for i in range(len(words) - n + 1) if tuple(words[i : i + n]) in theirs]
    spans: list[str] = []
    i = 0
    while i < len(hits):
        start = end = hits[i]
        while i + 1 < len(hits) and hits[i + 1] <= end + 1:
            i += 1
            end = hits[i]
        spans.append(" ".join(words[start : end + n]))
        i += 1
    return sorted(spans, key=len, reverse=True)


def drop_sentences_with(draft: str, spans: list[str]) -> str:
    """Last resort for a quote that survived paraphrasing: remove each
    sentence that contains one."""
    keep = []
    for sentence in stylo.raw_sentences(draft) or [draft]:
        joined = " ".join(stylo.words(strip_markers(sentence)))
        if not any(span in joined for span in spans):
            keep.append(sentence)
    return " ".join(keep)


# ---------------------------------------------------------------------------
# The graph


def build_graph(deps: DraftDeps):
    def charge(state: DraftState, t_in: int, t_out: int) -> dict:
        return {"tokens_in": state.get("tokens_in", 0) + t_in, "tokens_out": state.get("tokens_out", 0) + t_out}

    def classify_intent(state: DraftState) -> dict:
        message = state["message"]
        update: dict[str, Any] = {"intent": "other", "topic": message[:300], "people": []}
        try:
            raw, t_in, t_out = deps.classify(CLASSIFY_PROMPT.format(message=message[:6000]))
            update.update(charge(state, t_in, t_out))
            data = _json(raw)
            if data.get("intent") in INTENTS:
                update["intent"] = data["intent"]
            if isinstance(data.get("topic"), str) and data["topic"].strip():
                update["topic"] = data["topic"].strip()[:300]
            if not state.get("language") and data.get("language") in LANGUAGE_NAMES:
                update["language"] = data["language"]
            update["people"] = [
                {"name": str(p.get("name", "")).strip(), "public": bool(p.get("public"))}
                for p in data.get("people") or []
                if isinstance(p, dict) and str(p.get("name", "")).strip()
            ]
        except Exception as e:  # noqa: BLE001 — fail-soft: draft without the classification
            logger.warning("echo draft: classify failed: %s", e)
        language = update.get("language") or state.get("language") or deps.language_of(message)
        update["language"] = language if language in LANGUAGE_NAMES else "en"
        acknowledged = {n.casefold() for n in state.get("acknowledge_names") or []}
        update["needs_confirmation"] = [
            p["name"] for p in update["people"] if not p["public"] and p["name"].casefold() not in acknowledged
        ]
        return update

    def route_after_classify(state: DraftState) -> str:
        return "stop" if state.get("needs_confirmation") else "go"

    def retrieve_relevant_knowledge(state: DraftState) -> dict:
        return {"knowledge": deps.knowledge(state["topic"])}

    def retrieve_voice_signals(state: DraftState) -> dict:
        return {
            "trait_card": deps.signals(state["topic"], state["language"]),
            "exemplars": deps.exemplars(state["language"]),
        }

    def retrieve_personal_context(state: DraftState) -> dict:
        return {"facts": deps.facts(state["topic"])}

    def _draft_prompt(state: DraftState) -> str:
        return DRAFT_PROMPT.format(
            trait_card=_bullets(state.get("trait_card") or []),
            exemplars="\n\n".join(f"[{i + 1}] {e}" for i, e in enumerate(state.get("exemplars") or [])) or "(none yet)",
            facts=_numbered(state.get("facts") or []),
            knowledge=_numbered(state.get("knowledge") or []),
            message=state["message"],
            language_name=LANGUAGE_NAMES[state["language"]],
            register=state.get("register") or "that fits the message",
            audience=state.get("audience") or "the person who sent the message",
        )

    def draft(state: DraftState) -> dict:
        prompt = _draft_prompt(state)
        raw, t_in, t_out = deps.draft(prompt)
        return {"draft_prompt": prompt, "candidates": [{"draft": raw.strip()}], "rounds": 0, **charge(state, t_in, t_out)}

    def self_critique(state: DraftState) -> dict:
        candidates = list(state["candidates"])
        latest = candidates[-1]
        try:
            raw, t_in, t_out = deps.critique(CRITIQUE_PROMPT.format(
                trait_card=_bullets(state.get("trait_card") or []),
                exemplars="\n\n".join(state.get("exemplars") or []) or "(none yet)",
                knowledge=_numbered((state.get("knowledge") or []) + (state.get("facts") or [])),
                draft=latest["draft"],
            ))
            data = _json(raw)
            scores = {k: max(1.0, min(5.0, float(data.get(k, 0) or 0))) for k in ("tone", "vocabulary", "structure", "topicality", "grounded")}
            latest = {**latest, "scores": scores, "notes": [str(n)[:300] for n in data.get("notes") or [] if str(n).strip()][:8]}
            spent = charge(state, t_in, t_out)
        except Exception as e:  # noqa: BLE001 — fail-soft: keep the draft, say the check did not run
            logger.warning("echo draft: critique failed: %s", e)
            latest = {**latest, "scores": None, "notes": ["The voice check could not run for this draft."]}
            spent = {}
        candidates[-1] = latest
        return {"candidates": candidates, "rounds": state.get("rounds", 0) + 1, **spent}

    def _voice(c: dict) -> float:
        s = c.get("scores")
        return (s["tone"] + s["vocabulary"] + s["structure"] + s["topicality"]) / 4 if s else 0.0

    def route_after_critique(state: DraftState) -> str:
        latest = state["candidates"][-1]
        s = latest.get("scores")
        if s is None:
            return "finalize"
        good = _voice(latest) >= settings.ECHO_DRAFT_CRITIQUE_TARGET and s["grounded"] >= 4
        if good or state.get("rounds", 0) >= settings.ECHO_DRAFT_CRITIQUE_ROUNDS:
            return "finalize"
        return "revise"

    def revise(state: DraftState) -> dict:
        latest = state["candidates"][-1]
        raw, t_in, t_out = deps.draft(REVISE_PROMPT.format(
            draft_prompt=state["draft_prompt"], draft=latest["draft"], notes=_bullets(latest.get("notes") or []),
        ))
        return {"candidates": state["candidates"] + [{"draft": raw.strip()}], **charge(state, t_in, t_out)}

    def finalize(state: DraftState) -> dict:
        # Knockout: the best-scored candidate, the latest on a tie.
        best = max(enumerate(state["candidates"]), key=lambda ic: (_voice(ic[1]), ic[1].get("scores", {}) and ic[1]["scores"]["grounded"] or 0, ic[0]))[1]
        text = best["draft"]
        notes = list(best.get("notes") or [])
        flags: list[str] = []
        spent = {}
        third_party = [i.text for i in (state.get("knowledge") or []) if i.third_party]
        spans = verbatim_spans(text, third_party)
        if spans:
            raw, t_in, t_out = deps.draft(PARAPHRASE_PROMPT.format(
                draft_prompt=state["draft_prompt"], draft=text, spans=_bullets(spans),
            ))
            spent = charge(state, t_in, t_out)
            text = raw.strip()
            left = verbatim_spans(text, third_party)
            if left:
                text = drop_sentences_with(text, left)
                notes.append("A sentence that repeated a source word for word was removed.")
                flags.append("verbatim_removed")
        items = {i.marker: i for i in (state.get("knowledge") or []) + (state.get("facts") or [])}
        citations = [
            {"kind": items[m].kind, "label": items[m].label, **({"url": items[m].url} if items[m].url else {})}
            for m in cited_markers(text) if m in items
        ]
        if not citations and state.get("intent") in ("question", "opinion", "recommendation"):
            flags.append("ungrounded")
            notes.append("Nothing in your library or notes backed this reply; check every claim before sending.")
        s = best.get("scores")
        return {
            "result": {
                "draft": strip_markers(text),
                "citations": citations,
                "deviation_notes": notes,
                "flags": flags,
                "voice_match_score": round(_voice(best) / 5 * 100, 1) if s else 0.0,
                "confidence": round(s["grounded"] / 5, 2) if s else 0.0,
                "critique_rounds": state.get("rounds", 0),
            },
            **spent,
        }

    g = StateGraph(DraftState)
    for name, fn in (
        ("classify_intent", classify_intent),
        ("retrieve_relevant_knowledge", retrieve_relevant_knowledge),
        ("retrieve_voice_signals", retrieve_voice_signals),
        ("retrieve_personal_context", retrieve_personal_context),
        ("draft", draft),
        ("self_critique_against_voice", self_critique),
        ("revise", revise),
        ("finalize", finalize),
    ):
        g.add_node(name, fn)
    g.set_entry_point("classify_intent")
    g.add_conditional_edges("classify_intent", route_after_classify, {"stop": END, "go": "retrieve_relevant_knowledge"})
    g.add_edge("retrieve_relevant_knowledge", "retrieve_voice_signals")
    g.add_edge("retrieve_voice_signals", "retrieve_personal_context")
    g.add_edge("retrieve_personal_context", "draft")
    g.add_edge("draft", "self_critique_against_voice")
    g.add_conditional_edges("self_critique_against_voice", route_after_critique, {"revise": "revise", "finalize": "finalize"})
    g.add_edge("revise", "self_critique_against_voice")
    g.add_edge("finalize", END)
    return g.compile()


def run_echo_draft(
    deps: DraftDeps,
    *,
    message: str,
    audience: str | None = None,
    register: str | None = None,
    language: str | None = None,
    acknowledge_names: list[str] | None = None,
) -> DraftState:
    """Run the graph. The returned state carries ``needs_confirmation`` (and
    no ``result``) when a private person must be confirmed first."""
    return build_graph(deps).invoke({
        "message": message,
        "audience": audience,
        "register": register,
        "language": language,
        "acknowledge_names": list(acknowledge_names or []),
        "tokens_in": 0,
        "tokens_out": 0,
    })
