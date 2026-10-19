"""Scoring for the code-mixing detectors against the hand-labelled set.

The labelled set lives in `tests/fixtures/code_mixing/labelled_units.json`.
Each unit carries the source text and an ANNOTATION of it:

- `{...}` marks a Hindi/Urdu span, `|...|` an English span, `<...>` a span
  that is neither (names, language names, crore/lakh, non-speech tags);
- unmarked words take the unit's `base` language ("en" or "hi").

`gold_tags` parses an annotation back into one tag per `tokenize()` token
and refuses an annotation whose markup does not strip to the exact source
text, so a labelling slip fails loudly instead of shifting every tag after
it. Method and results: docs/notes/2026-10-19-code-mixing-detection.md.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.code_mixing_service import tokenize

FIXTURE = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "code_mixing"
    / "labelled_units.json"
)

_OPEN = {"{": "hi", "|": "en", "<": "ne"}
_CLOSE = {"}": "{", ">": "<"}


def load_units(path: Path | None = None) -> list[dict]:
    return json.loads((path or FIXTURE).read_text(encoding="utf-8"))


def gold_tags(unit: dict) -> list[str]:
    """One gold tag per token of `unit["text"]`."""
    ann = unit["annotation"]
    if ann == "=":
        ann = unit["text"]
    base = unit["base"]
    plain: list[str] = []
    lang_at: list[str] = []
    stack: list[str] = []
    for ch in ann:
        if ch in ("{", "<") or (ch == "|" and (not stack or stack[-1] != "|")):
            stack.append(ch)
            continue
        if ch in _CLOSE or (ch == "|" and stack and stack[-1] == "|"):
            opener = _CLOSE.get(ch, "|")
            if not stack or stack[-1] != opener:
                raise ValueError(f"{unit['id']}: unbalanced {ch!r}")
            stack.pop()
            continue
        plain.append(ch)
        lang_at.append(_OPEN[stack[-1]] if stack else base)
    if stack:
        raise ValueError(f"{unit['id']}: unclosed {stack[-1]!r}")
    text = "".join(plain)
    if text != unit["text"]:
        raise ValueError(f"{unit['id']}: annotation does not strip to the source text")
    tags = []
    for tok in tokenize(text):
        if tok.script == "Number":
            tags.append("ne")
        else:
            tags.append(lang_at[tok.start])
    return tags


def unit_class(tags: list[str], text: str) -> str:
    """english / romanised_hindi / mixed / other, from token tags."""
    from app.services import language_service

    if language_service.dominant_script(text) not in (None, "Latin"):
        return "other"
    c = Counter(tags)
    en, hi = c.get("en", 0), c.get("hi", 0)
    if en and hi:
        return "mixed"
    if hi:
        return "romanised_hindi"
    if en:
        return "english"
    return "other"


def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4),
            "tp": tp, "fp": fp, "fn": fn}


def score(units: list[dict], predicted: dict[str, list[str]]) -> dict[str, Any]:
    """Score predicted tags (unit id -> tags) against gold.

    Reports, per script group:
    - token-level P/R/F1 for the Hindi class, over tokens whose GOLD tag is
      en or hi (gold-neutral tokens — names, numbers — are not scored);
    - unit-level P/R for "contains Hindi" on Latin units: the
      honest-failure-mode metric — a missed unit is Hinglish passed
      through as English;
    - mean absolute error of the Hindi share per unit.
    Units with no prediction (an LLM batch failed) count as missing, not as
    all-English, and are reported separately.
    """
    out: dict[str, Any] = {}
    groups = {"latin": [], "devanagari": [], "all": []}
    missing = []
    for u in units:
        if u["id"] not in predicted or predicted[u["id"]] is None:
            missing.append(u["id"])
            continue
        g = gold_tags(u)
        p = predicted[u["id"]]
        if len(p) != len(g):
            raise ValueError(f"{u['id']}: {len(p)} predicted tags for {len(g)} tokens")
        latin = unit_class(g, u["text"]) != "other" or u["base"] == "en"
        groups["latin" if latin else "devanagari"].append((u, g, p))
        groups["all"].append((u, g, p))

    for name, rows in groups.items():
        tp = fp = fn = 0
        u_tp = u_fp = u_fn = u_tn = 0
        abs_err = []
        for u, g, p in rows:
            for gt, pt in zip(g, p):
                if gt == "ne":
                    continue
                if gt == "hi" and pt == "hi":
                    tp += 1
                elif gt != "hi" and pt == "hi":
                    fp += 1
                elif gt == "hi" and pt != "hi":
                    fn += 1
            scored = [(gt, pt) for gt, pt in zip(g, p) if gt != "ne"]
            if scored:
                g_share = sum(gt == "hi" for gt, _ in scored) / len(scored)
                p_share = sum(pt == "hi" for _, pt in scored) / len(scored)
                abs_err.append(abs(g_share - p_share))
            g_has = any(t == "hi" for t in g)
            p_has = any(pt == "hi" for gt, pt in zip(g, p) if gt != "ne")
            if g_has and p_has:
                u_tp += 1
            elif p_has and not g_has:
                u_fp += 1
            elif g_has and not p_has:
                u_fn += 1
            else:
                u_tn += 1
        out[name] = {
            "units": len(rows),
            "token_hindi": _prf(tp, fp, fn),
            "unit_contains_hindi": {**_prf(u_tp, u_fp, u_fn), "tn": u_tn},
            "hindi_share_mae": round(sum(abs_err) / len(abs_err), 4) if abs_err else 0.0,
        }
    out["missing_units"] = missing
    return out


def matrix_accuracy(units: list[dict], predicted: dict[str, str]) -> dict[str, Any]:
    """Matrix-language accuracy on the units where it is a real question:
    gold has both languages and a gold matrix of en or hi."""
    rows = []
    for u in units:
        if u["matrix"] not in ("en", "hi"):
            continue
        g = gold_tags(u)
        if not ("en" in g and "hi" in g):
            continue
        if u["id"] not in predicted or predicted[u["id"]] is None:
            continue
        rows.append((u["matrix"], predicted[u["id"]]))
    correct = sum(g == p for g, p in rows)
    confusion = Counter(f"{g}->{p}" for g, p in rows)
    return {
        "units": len(rows),
        "accuracy": round(correct / len(rows), 4) if rows else 0.0,
        "confusion": dict(sorted(confusion.items())),
    }


def gold_analysis(unit: dict) -> dict[str, Any]:
    """The labeller's version of `analyse_span`: gold shares and gold matrix."""
    g = gold_tags(unit)
    en, hi = g.count("en"), g.count("hi")
    return {
        "en_tokens": en,
        "hi_tokens": hi,
        "hi_share": round(hi / (en + hi), 4) if en + hi else 0.0,
        "matrix": unit["matrix"],
    }


def policy_agreement(
    units: list[dict], dominant: float | None = None, borrowing: float | None = None
) -> dict[str, Any]:
    """How often the rendering mode computed from the DETECTOR's analysis
    equals the mode computed from the GOLD analysis (T-1.16.2.3).

    The policy's thresholds are only as good as the decisions they produce
    on detector output: a threshold that sits where detector bias pushes
    spans across it flips modes on noise alone.
    """
    from app.services.code_mixing_service import analyse_span, rendering_mode

    agree: Counter[str] = Counter()
    total: Counter[str] = Counter()
    gold_modes: Counter[str] = Counter()
    flips: Counter[str] = Counter()
    for u in units:
        gold = gold_analysis(u)
        if not (gold["en_tokens"] or gold["hi_tokens"]):
            continue
        g = rendering_mode(gold, dominant, borrowing)
        p = rendering_mode(analyse_span(u["text"]), dominant, borrowing)
        gold_modes[g] += 1
        groups = ["all", "latin" if u["base"] == "en" else "devanagari"]
        if gold["en_tokens"] and gold["hi_tokens"]:
            groups.append("mixed")   # the units where the decision is not trivial
        for group in groups:
            total[group] += 1
            agree[group] += g == p
        if g != p:
            flips[f"{g}->{p}"] += 1
    return {
        "agreement": {k: round(agree[k] / total[k], 4) for k in total},
        "units": dict(total),
        "gold_modes": dict(sorted(gold_modes.items())),
        "flips": dict(sorted(flips.items())),
    }
