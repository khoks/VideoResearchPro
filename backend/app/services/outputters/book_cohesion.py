"""Book cohesion pass (S-6.1.3): framing prose around unchanged chapters.

``parameters.cohesion`` picks how much:

- ``none`` (default until the blind judgement says otherwise): the chapters
  in the order the user picked, as before.
- ``light``: one ``author_book_outline`` call. Reading order, parts (four or
  more chapters with real seams), a bridge paragraph into each chapter and a
  short introduction, all from the outline's own text.
- ``full``: the outline plus one ``author_book_prose`` call, which writes the
  introduction, bridges, conclusion and glossary from longer excerpts.

**Chapters are never rewritten** (the plan's guarantee against invented
citations, the S-1.14.9 class of defect): the model sees digests and writes
framing only, and whatever it returns is cleaned of links, footnote markers,
headings and HTML before it reaches the manuscript.

**Fail-soft, disclosed** (the D-056 posture): a failed or unusable call
leaves the book as the lower level would have made it, and the manuscript's
processing note says which call failed. Nothing is silently dropped.

Every call's tokens, model and cost are kept (`Cohesion.usage()`), stored on
the output and shown beside it; `estimate()` gives the same figures before
generation from character counts.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agents.prompts import author_prompts
from app.services import cost_estimator, llm_service
from app.services.llm_routing import resolve_config
from app.services.output_service import OutputError

logger = logging.getLogger(__name__)

LEVELS = ("none", "light", "full")
DEFAULT_LEVEL = "none"
OUTLINE_USE_CASE = "author_book_outline"
PROSE_USE_CASE = "author_book_prose"

# Words of each chapter the model sees. The outline needs enough to place a
# chapter; the prose needs enough to introduce and define without guessing.
OUTLINE_EXCERPT_WORDS = 350
PROSE_EXCERPT_WORDS = 1_200
MAX_HEADINGS = 24
# Completion budgets include reasoning tokens on OpenAI models (the D-052
# trap), so they are generous; the visible output is a few thousand tokens.
OUTLINE_MAX_TOKENS = 16_000
PROSE_MAX_TOKENS = 24_000
# What the output side is expected to be, for the estimate: the largest
# billed on the S-6.1.3 trial books (outline 1,003-1,738 tokens with its
# reasoning, prose 2,631-3,094), rounded up.
OUTLINE_OUTPUT_TOKENS_EST = 1_800
PROSE_OUTPUT_TOKENS_EST = 3_500

BRIDGE_MAX_WORDS = 120
SECTION_MAX_WORDS = 520
BRIEF_MAX_WORDS = 160
GLOSSARY_MAX_TERMS = 25
DEFINITION_MAX_WORDS = 60

_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\s]*\)")
_FOOTNOTE_REF = re.compile(r"\[\^[^\]\s]+\]")
# Line-anchored patterns use [ \t], never \s: \s matches the newline, so a
# pattern anchored on a blank line would swallow it and merge paragraphs.
_HEADING_LINE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.M)
_QUOTE_MARK = re.compile(r"^[ \t]*>[ \t]?", re.M)
_TABLE_ROW = re.compile(r"^[ \t]*\|.*\|[ \t]*$", re.M)
_HTML_TAG = re.compile(r"</?[A-Za-z][^>\n]*>")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SUMMARY_HEADING = re.compile(r"summary|overview|introduction|key (findings|takeaways)", re.I)


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChapterDigest:
    number: int  # the chapter's position in the user's order, 1-based
    title: str
    headings: list[str]
    words: int
    body: str  # the chapter's Markdown, before citations are numbered

    def excerpt(self, max_words: int) -> str:
        """The chapter's summary section when it has one, else its opening;
        links, footnotes and fenced code reduced to text."""
        lines = _plain_lines(self.body)
        start = 0
        for i, (is_heading, text) in enumerate(lines):
            if is_heading and _SUMMARY_HEADING.search(text):
                start = i + 1
                break
        words: list[str] = []
        out: list[str] = []
        for is_heading, text in lines[start:]:
            if is_heading:
                if out and words:
                    out.append("")
                out.append(f"[{text}]")
                continue
            remaining = max_words - len(words)
            if remaining <= 0:
                break
            chunk = text.split()[:remaining]
            words.extend(chunk)
            out.append(" ".join(chunk))
        return "\n".join(out).strip()

    def as_prompt(self, max_words: int) -> dict:
        return {
            "number": self.number,
            "title": self.title,
            "words": self.words,
            "headings": self.headings[:MAX_HEADINGS],
            "excerpt": self.excerpt(max_words),
        }


def _plain_lines(markdown: str) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []
    in_fence = False
    for raw in (markdown or "").splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence or not raw.strip():
            continue
        is_heading = bool(_HEADING_LINE.match(raw))
        text = _LINK.sub(r"\1", _FOOTNOTE_REF.sub("", raw))
        text = _HEADING_LINE.sub("", text).strip()
        if text and not set(text) <= set("|-: "):  # table separator rows
            out.append((is_heading, text))
    return out


def digest(number: int, title: str, body: str) -> ChapterDigest:
    lines = _plain_lines(body)
    return ChapterDigest(
        number=number,
        title=title,
        headings=[t for h, t in lines if h],
        words=sum(len(t.split()) for h, t in lines if not h),
        body=body,
    )


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class CallUsage:
    use_case: str
    provider: str
    model: str
    reasoning: str
    ok: bool
    seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "use_case": self.use_case,
            "provider": self.provider,
            "model": self.model,
            "reasoning": self.reasoning,
            "ok": self.ok,
            "seconds": round(self.seconds, 1),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 4),
            "error": self.error,
        }


@dataclass
class Cohesion:
    level: str
    order: list[int]
    parts: list[tuple[str, list[int]]] = field(default_factory=list)
    introduction: str = ""
    bridges: dict[int, str] = field(default_factory=dict)
    conclusion: str = ""
    glossary: list[tuple[str, str]] = field(default_factory=list)
    calls: list[CallUsage] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # What the manuscript actually got, which can be less than asked for.
    applied: str = "none"

    def usage(self) -> dict:
        costs = [c.cost_usd for c in self.calls]
        return {
            "cohesion": {"requested": self.level, "applied": self.applied},
            "calls": [c.as_dict() for c in self.calls],
            "input_tokens": sum(c.input_tokens or 0 for c in self.calls),
            "output_tokens": sum(c.output_tokens or 0 for c in self.calls),
            "cost_usd": round(sum(costs), 4) if costs and all(c is not None for c in costs) else None,
        }

    @property
    def model_labels(self) -> list[str]:
        return sorted({c.model for c in self.calls if c.ok})


def level_from(params: dict[str, Any]) -> str:
    raw = params.get("cohesion", DEFAULT_LEVEL)
    level = str(raw).strip().lower() if raw is not None else DEFAULT_LEVEL
    if level not in LEVELS:
        raise OutputError(f"cohesion must be one of {', '.join(LEVELS)}; got {raw!r}.")
    return level


# ---------------------------------------------------------------------------
# Cleaning what the model returns
# ---------------------------------------------------------------------------


def clean_prose(text: Any, max_words: int) -> str:
    """Model prose made safe to splice into the manuscript: no links (kept as
    text), no footnote markers, no headings, no HTML, no code fences,
    paragraphs kept, and at most ``max_words`` words (cut at a sentence end
    when one is near)."""
    if not isinstance(text, str):
        return ""
    s = text.replace("\r\n", "\n")
    s = re.sub(r"```.*?```", "", s, flags=re.S)
    s = _LINK.sub(r"\1", s)
    s = _FOOTNOTE_REF.sub("", s)
    s = _HTML_TAG.sub("", s)
    s = _HEADING_LINE.sub("", s)
    s = _QUOTE_MARK.sub("", s)
    s = _TABLE_ROW.sub("", s)
    paragraphs = [re.sub(r"[ \t]+", " ", p).strip() for p in re.split(r"\n\s*\n", s)]
    paragraphs = [re.sub(r"\s*\n\s*", " ", p) for p in paragraphs if p]
    out: list[str] = []
    budget = max_words
    for p in paragraphs:
        words = p.split()
        if len(words) <= budget:
            out.append(p)
            budget -= len(words)
            continue
        if budget > 0:
            cut = " ".join(words[:budget])
            end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
            out.append(cut[: end + 1] if end > len(cut) // 2 else cut + " …")
        break
    return "\n\n".join(out).strip()


def _single_paragraph(text: Any, max_words: int) -> str:
    return " ".join(clean_prose(text, max_words).split("\n\n")).strip()


def _parse_json(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the response")
    # strict=False: prose models put real newlines inside JSON strings
    # (paragraph breaks), which strict parsing rejects as control characters.
    # Found on the first live run (claude-sonnet-5, 2026-10-19).
    value = json.loads(raw[start : end + 1], strict=False)
    if not isinstance(value, dict):
        raise ValueError("the response is not a JSON object")
    return value


_SECTION_MARKER = re.compile(
    r"^[ \t]*={3,}[ \t]*(INTRODUCTION|CONCLUSION|GLOSSARY|BRIDGE[ \t]+(\d+))[ \t]*={3,}[ \t]*$", re.M | re.I
)


def _parse_prose(raw: str) -> dict:
    """The prose call's marked sections (see `author_prompts.PROSE_SYSTEM`) as
    the same dict the JSON form would give. A model that answers in JSON
    anyway is still read."""
    markers = list(_SECTION_MARKER.finditer(raw))
    if not markers:
        return _parse_json(raw)
    out: dict[str, Any] = {"introduction": "", "bridges": [], "conclusion": "", "glossary": []}
    for i, m in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(raw)
        text = raw[m.end() : end].strip()
        name = m.group(1).upper()
        if name == "INTRODUCTION":
            out["introduction"] = text
        elif name == "CONCLUSION":
            out["conclusion"] = text
        elif name == "GLOSSARY":
            for line in text.splitlines():
                line = line.strip().lstrip("-*• ").strip()
                if "::" in line:
                    term, definition = line.split("::", 1)
                    out["glossary"].append({"term": term.strip(), "definition": definition.strip()})
        else:
            out["bridges"].append({"chapter": int(m.group(2)), "text": text})
    if not any(out.values()):
        raise ValueError("the marked sections are empty")
    return out


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------


Invoker = Callable[[str, str, str, int], Any]


def _default_invoke(use_case: str, system: str, user: str, max_tokens: int):
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = llm_service.get_llm_for(use_case, temperature=0.2, max_tokens=max_tokens)
    return llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])


def _usage(response) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict) and (isinstance(usage.get("input_tokens"), int) or isinstance(usage.get("output_tokens"), int)):
        return usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
    meta = getattr(response, "response_metadata", None)
    token_usage = meta.get("token_usage") if isinstance(meta, dict) else None
    if isinstance(token_usage, dict):
        return token_usage.get("prompt_tokens") or 0, token_usage.get("completion_tokens") or 0
    return None, None


def _call(
    use_case: str,
    system: str,
    user: str,
    max_tokens: int,
    invoke: Invoker,
    parse: Callable[[str], dict] = _parse_json,
) -> tuple[dict | None, CallUsage]:
    cfg = resolve_config(use_case)
    t0 = time.perf_counter()
    record = CallUsage(use_case, cfg.provider, cfg.model, cfg.reasoning, ok=False, seconds=0.0)
    try:
        response = invoke(use_case, system, user, max_tokens)
        record.input_tokens, record.output_tokens = _usage(response)
        if record.input_tokens is not None:
            record.cost_usd = cost_estimator.call_cost(cfg.model, record.input_tokens, record.output_tokens or 0)
        parsed = parse(llm_service.response_text(response))
        record.ok = True
        return parsed, record
    except Exception as e:  # noqa: BLE001 — fail-soft, disclosed
        logger.warning("book cohesion: %s failed: %s", use_case, e)
        record.error = f"{type(e).__name__}: {str(e)[:300]}"
        return None, record
    finally:
        record.seconds = time.perf_counter() - t0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _chapter_number(value: Any, valid: set[int]) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n in valid else None


def _validate_outline(raw: dict, digests: list[ChapterDigest], notes: list[str]) -> dict:
    """The outline reduced to what can be trusted: a full permutation (else
    the user's order), parts that cover the order in consecutive runs (else
    none), bridges for known chapters other than the first."""
    numbers = [d.number for d in digests]
    valid = set(numbers)
    order = [n for n in (_chapter_number(v, valid) for v in raw.get("order") or []) if n is not None]
    if sorted(order) != sorted(numbers) or len(order) != len(numbers):
        if raw.get("order"):
            notes.append("The suggested reading order did not list every chapter exactly once, so your order was kept.")
        order = list(numbers)

    parts: list[tuple[str, list[int]]] = []
    raw_parts = raw.get("parts") or []
    if isinstance(raw_parts, list) and raw_parts and len(numbers) >= 4:
        flat: list[int] = []
        for p in raw_parts:
            if not isinstance(p, dict):
                flat = []
                break
            chapters = [n for n in (_chapter_number(v, valid) for v in p.get("chapters") or []) if n is not None]
            title = _single_paragraph(p.get("title"), 12)
            if not chapters or not title:
                flat = []
                break
            parts.append((title, chapters))
            flat.extend(chapters)
        if flat != order or len(parts) < 2:
            if raw_parts and flat != order:
                notes.append("The suggested parts did not follow the reading order, so the book has no parts.")
            parts = []

    bridges: dict[int, str] = {}
    for b in raw.get("bridges") or []:
        if not isinstance(b, dict):
            continue
        n = _chapter_number(b.get("chapter"), valid)
        text = _single_paragraph(b.get("text"), BRIDGE_MAX_WORDS)
        if n is not None and n != order[0] and text:
            bridges[n] = text

    terms = [t.strip() for t in raw.get("glossary_terms") or [] if isinstance(t, str) and t.strip()]
    return {
        "order": order,
        "parts": parts,
        "bridges": bridges,
        "introduction_brief": clean_prose(raw.get("introduction_brief"), BRIEF_MAX_WORDS),
        "conclusion_brief": clean_prose(raw.get("conclusion_brief"), BRIEF_MAX_WORDS),
        "glossary_terms": terms[:GLOSSARY_MAX_TERMS],
    }


def _glossary(raw: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        term = _single_paragraph(entry.get("term"), 8).strip(" *_")
        definition = _single_paragraph(entry.get("definition"), DEFINITION_MAX_WORDS)
        if term and definition and term.lower() not in seen:
            seen.add(term.lower())
            out.append((term, definition))
    return sorted(out, key=lambda td: td[0].lower())[:GLOSSARY_MAX_TERMS]


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def plan(
    digests: list[ChapterDigest],
    book_title: str,
    level: str,
    *,
    invoke: Invoker | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> Cohesion:
    """Run the cohesion pass for ``level``. Never raises for a model failure:
    the result says what was applied and why not more."""
    invoke = invoke or _default_invoke
    result = Cohesion(level=level, order=[d.number for d in digests])
    if level == "none" or not digests:
        return result

    if progress:
        progress(6, "Planning the book")
    raw, record = _call(
        OUTLINE_USE_CASE,
        author_prompts.OUTLINE_SYSTEM,
        author_prompts.outline_user_prompt(book_title, [d.as_prompt(OUTLINE_EXCERPT_WORDS) for d in digests]),
        OUTLINE_MAX_TOKENS,
        invoke,
    )
    result.calls.append(record)
    if raw is None:
        result.notes.append(f"The book outline call failed ({record.error}); the chapters appear in your order with no added framing.")
        return result

    outline = _validate_outline(raw, digests, result.notes)
    result.order = outline["order"]
    result.parts = outline["parts"]
    result.bridges = outline["bridges"]
    result.introduction = outline["introduction_brief"]
    result.applied = "light"
    if level == "light":
        return result

    if progress:
        progress(8, "Writing the introduction, bridges, conclusion and glossary")
    # The prose call sees chapters numbered in READING order, as the printed
    # book numbers them. With the user's numbering, a reordered book's
    # introduction said "the chapters are printed in the order 4, 2, 1, 3"
    # (first live trial, 2026-10-19).
    by_number = {d.number: d for d in digests}
    position = {n: i for i, n in enumerate(result.order, start=1)}
    original = {i: n for n, i in position.items()}
    plan_for_prompt = {
        "order": list(range(1, len(result.order) + 1)),
        "parts": [{"title": t, "chapters": [position[n] for n in c]} for t, c in result.parts],
        "bridges": [{"chapter": position[n], "text": t} for n, t in result.bridges.items()],
        "introduction_brief": outline["introduction_brief"],
        "conclusion_brief": outline["conclusion_brief"],
        "glossary_terms": outline["glossary_terms"],
    }
    prose_digests = [{**by_number[n].as_prompt(PROSE_EXCERPT_WORDS), "number": position[n]} for n in result.order]
    raw, record = _call(
        PROSE_USE_CASE,
        author_prompts.PROSE_SYSTEM,
        author_prompts.prose_user_prompt(book_title, plan_for_prompt, prose_digests),
        PROSE_MAX_TOKENS,
        invoke,
        parse=_parse_prose,
    )
    result.calls.append(record)
    if raw is None:
        result.notes.append(
            f"The call that writes the introduction, conclusion and glossary failed ({record.error}); "
            "the book carries the outline's shorter introduction and bridges instead."
        )
        return result

    introduction = clean_prose(raw.get("introduction"), SECTION_MAX_WORDS)
    conclusion = clean_prose(raw.get("conclusion"), SECTION_MAX_WORDS)
    if introduction:
        result.introduction = introduction
    result.conclusion = conclusion
    for b in raw.get("bridges") or []:
        if isinstance(b, dict):
            pos = _chapter_number(b.get("chapter"), set(original))
            text = _single_paragraph(b.get("text"), BRIDGE_MAX_WORDS)
            if pos is not None and pos != 1 and text:
                result.bridges[original[pos]] = text
    result.glossary = _glossary(raw.get("glossary"))
    result.applied = "full"
    return result


# ---------------------------------------------------------------------------
# Estimate
# ---------------------------------------------------------------------------


# Characters per billed input token, measured on the S-6.1.3 trial books
# (2026-10-19, English and Hinglish chapters): the OpenAI outline billed 0.91x
# and the Anthropic prose 1.47x a flat chars/4 count.
_CHARS_PER_TOKEN = {"openai": 4.4, "anthropic": 2.75}
_DEFAULT_CHARS_PER_TOKEN = 3.5


def _tokens(text: str, use_case: str) -> int:
    provider = resolve_config(use_case).provider  # type: ignore[arg-type]
    return max(1, int(len(text) / _CHARS_PER_TOKEN.get(provider, _DEFAULT_CHARS_PER_TOKEN)))


def estimate(digests: list[ChapterDigest], book_title: str, level: str) -> dict:
    """What the pass will cost before it runs, from the prompts it would send
    (characters / 4) and the expected output size."""
    calls: list[tuple[str, int, int]] = []
    if level in ("light", "full") and digests:
        outline_in = _tokens(
            author_prompts.OUTLINE_SYSTEM
            + author_prompts.outline_user_prompt(book_title, [d.as_prompt(OUTLINE_EXCERPT_WORDS) for d in digests]),
            OUTLINE_USE_CASE,
        )
        calls.append((OUTLINE_USE_CASE, outline_in, OUTLINE_OUTPUT_TOKENS_EST))
    if level == "full" and digests:
        fake_plan = {"order": [d.number for d in digests], "parts": [], "bridges": [], "introduction_brief": "x" * 600,
                     "conclusion_brief": "x" * 400, "glossary_terms": ["term"] * 20}
        prose_in = _tokens(
            author_prompts.PROSE_SYSTEM
            + author_prompts.prose_user_prompt(book_title, fake_plan, [d.as_prompt(PROSE_EXCERPT_WORDS) for d in digests]),
            PROSE_USE_CASE,
        )
        calls.append((PROSE_USE_CASE, prose_in, PROSE_OUTPUT_TOKENS_EST))
    return {"cohesion": level, **cost_estimator.estimate_calls(calls)}
