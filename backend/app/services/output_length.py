"""Output-length policy: corpus brackets with per-bracket defaults, plus an
optional user override — R4 / D-064.

THE CONSTRAINT THAT SHAPES THIS MODULE
--------------------------------------
A per-bracket **cap** is literally the defect D-055/D-056 removed: the report
pipeline used to pin `max_tokens=3000` on map and `6000` on reduce regardless
of the work in front of them, and a 200-video job produced a report citing 2
channels out of 92. D-056's rule is "completion budgets derive from the work,
not constants", and D-062 then showed length intuitions here were wrong twice
(opus ran 2.6x longer AND ~1.4x denser — the extra length carried extra
information, not padding).

So brackets here are **not** caps. They do two things:

1. Scale the DERIVED budget by a multiplier. The budget still tracks corpus
   size continuously; the multiplier only shifts where on that curve we sit.
   A 'deep' setting on a small corpus never exceeds what the corpus supports,
   because the derived figure is still the base.
2. Give the composer explicit prose guidance about target depth, which is what
   actually moves output length — D-062 measured that a model writes to the
   brief it is given far more than to the token ceiling it is handed.

Extraction is deliberately NOT scaled. Fidelity of what we pull out of the
corpus is not a user preference; only how much of it gets written up is.
"""
from __future__ import annotations

from typing import Literal

OutputLength = Literal["auto", "brief", "standard", "deep"]

VALID_OUTPUT_LENGTHS: tuple[str, ...] = ("auto", "brief", "standard", "deep")

# Corpus size brackets, keyed off the statistics the report agent already
# computes. Thresholds chosen from real jobs: the reference corpus is 200
# videos / 1,057,331 words (xlarge); a smoke-test job is 3 videos (small).
_BRACKETS: tuple[tuple[str, int, int], ...] = (
    # (name, min_videos, min_words)
    ("xlarge", 120, 500_000),
    ("large", 40, 150_000),
    ("medium", 10, 30_000),
    ("small", 0, 0),
)

# Default depth per bracket. Small corpora get proportionally MORE written up
# per source (there is little to say, so say it fully); very large corpora are
# already enormous at 1.0 and do not need inflating.
_BRACKET_DEFAULT: dict[str, float] = {
    "small": 1.25,
    "medium": 1.1,
    "large": 1.0,
    "xlarge": 1.0,
}

# Explicit user override, applied INSTEAD of the bracket default.
_USER_MULTIPLIER: dict[str, float] = {
    "brief": 0.45,
    "standard": 1.0,
    "deep": 1.6,
}

_GUIDANCE: dict[str, str] = {
    "brief": (
        "LENGTH: aim for a tight, high-signal treatment. Prefer the most "
        "load-bearing claims over exhaustive coverage, and keep prose compact. "
        "Do NOT drop attribution or specific figures to save space — cut whole "
        "low-value points instead of thinning good ones."
    ),
    "standard": (
        "LENGTH: cover the material proportionally to its substance."
    ),
    "deep": (
        "LENGTH: this reader wants depth. Develop the reasoning behind claims, "
        "surface secondary and dissenting points, and follow threads across "
        "sources rather than stopping at the headline. Length must be earned "
        "by content — never pad, restate, or inflate."
    ),
}


def corpus_bracket(statistics: dict | None) -> str:
    """Classify a corpus by size. Falls back to 'small' on missing stats."""
    stats = statistics or {}
    videos = int(stats.get("video_count") or 0)
    words = int(stats.get("total_words") or 0)
    for name, min_v, min_w in _BRACKETS:
        if videos >= min_v or words >= min_w:
            return name
    return "small"


def resolve_scale(statistics: dict | None, user_pref: str | None) -> float:
    """Multiplier applied to the DERIVED completion budget.

    ``user_pref`` of None/'auto' uses the bracket default; anything else is an
    explicit override. Unknown values fall back to the bracket default rather
    than raising — an odd value in the DB must never fail a job.
    """
    pref = (user_pref or "auto").lower()
    if pref in _USER_MULTIPLIER:
        return _USER_MULTIPLIER[pref]
    return _BRACKET_DEFAULT.get(corpus_bracket(statistics), 1.0)


def guidance(statistics: dict | None, user_pref: str | None) -> str:
    """Prose guidance for the composer. Empty string when nothing to say."""
    pref = (user_pref or "auto").lower()
    if pref in _GUIDANCE:
        return _GUIDANCE[pref]
    # 'auto' on a small corpus still benefits from being told to be thorough,
    # since there is little material and a terse default reads as thin.
    if corpus_bracket(statistics) == "small":
        return (
            "LENGTH: the corpus is small, so treat each source thoroughly "
            "rather than summarising briefly."
        )
    return ""


def describe(statistics: dict | None, user_pref: str | None) -> str:
    """One-line log/debug description of the resolved policy."""
    return (
        f"bracket={corpus_bracket(statistics)} pref={(user_pref or 'auto')} "
        f"scale={resolve_scale(statistics, user_pref):.2f}"
    )
