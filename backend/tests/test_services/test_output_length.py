"""R4 / D-064 — corpus brackets and the optional user depth override.

The invariant these protect: brackets must NEVER become caps. D-055/D-056
removed exactly that defect (hardcoded 3,000/6,000 completion caps that made a
200-video job cite 2 channels out of 92), and D-062 showed length intuitions
here were wrong twice. So the multiplier scales a DERIVED budget and the
guidance changes the brief — neither replaces the corpus-driven figure.
"""
from unittest.mock import MagicMock, patch

from app.agents import report_agent as ra
from app.services import output_length as ol


XL = {"video_count": 200, "total_words": 1_057_331}   # the reference corpus
SMALL = {"video_count": 3, "total_words": 5_000}


# --- brackets ---------------------------------------------------------------
def test_brackets_classify_real_corpora() -> None:
    assert ol.corpus_bracket(XL) == "xlarge"
    assert ol.corpus_bracket({"video_count": 50, "total_words": 200_000}) == "large"
    assert ol.corpus_bracket({"video_count": 15, "total_words": 50_000}) == "medium"
    assert ol.corpus_bracket(SMALL) == "small"


def test_missing_statistics_never_raise() -> None:
    assert ol.corpus_bracket(None) == "small"
    assert ol.corpus_bracket({}) == "small"
    assert ol.resolve_scale(None, None) > 0


# --- user override ----------------------------------------------------------
def test_explicit_preference_overrides_the_bracket_default() -> None:
    assert ol.resolve_scale(XL, "brief") < ol.resolve_scale(XL, None)
    assert ol.resolve_scale(XL, "deep") > ol.resolve_scale(XL, None)
    assert ol.resolve_scale(XL, "standard") == 1.0


def test_auto_uses_the_bracket_default() -> None:
    """A small corpus is written up more fully per source; xlarge needs no
    inflation."""
    assert ol.resolve_scale(SMALL, None) > ol.resolve_scale(XL, None)
    assert ol.resolve_scale(XL, "auto") == ol.resolve_scale(XL, None)


def test_unknown_preference_falls_back_rather_than_raising() -> None:
    """A stale or hand-edited DB value must never fail a job."""
    assert ol.resolve_scale(XL, "enormous") == ol.resolve_scale(XL, None)
    assert ol.resolve_scale(XL, "") == ol.resolve_scale(XL, None)


def test_guidance_is_prose_for_explicit_prefs_and_empty_for_plain_auto() -> None:
    assert "tight" in ol.guidance(XL, "brief").lower()
    assert "depth" in ol.guidance(XL, "deep").lower()
    # Large corpus on auto: nothing to say, so say nothing.
    assert ol.guidance(XL, None) == ""
    # Small corpus on auto still benefits from a nudge.
    assert ol.guidance(SMALL, None) != ""


def test_deep_guidance_forbids_padding() -> None:
    """D-062: length must be earned by content, never by restatement."""
    g = ol.guidance(XL, "deep").lower()
    assert "pad" in g or "inflate" in g


# --- the anti-cap invariant -------------------------------------------------
def test_length_policy_scales_the_budget_but_never_caps_it() -> None:
    """'deep' on a small corpus must not exceed what the corpus supports: the
    derived material size is still the base of the calculation."""
    small_material = 1_000
    large_material = 100_000
    # Same preference, different corpora -> budget still tracks the material.
    assert (small_material * 1.2 * ol.resolve_scale(SMALL, "deep")) < (
        large_material * 1.2 * ol.resolve_scale(XL, "brief")
    )


def test_compose_applies_the_preference_to_completion_budgets() -> None:
    def _item(v: str) -> dict:
        return {
            "content": "c " + "x" * 400,
            "video_title": f"t-{v}",
            "video_url": f"https://youtu.be/{v}",
            "channel_name": f"ch-{v}",
            "timestamp_seconds": 0,
        }

    summaries = [{"facts": [_item(f"v{i}") for i in range(20)]}]

    def _run(pref):
        seen: list[int] = []

        def _fake(use_case, **kw):
            seen.append(kw.get("max_tokens"))
            m = MagicMock()
            m.invoke.return_value = MagicMock(content="<h2>Key Facts</h2>")
            return m

        with patch.object(ra, "get_llm_for", side_effect=_fake):
            ra.compose_report({
                "chunk_summaries": summaries,
                "statistics": XL,
                "job_type": "topic",
                "topic": "t",
                "output_length": pref,
            })
        # The FIRST call is the section compose; the executive summary that
        # follows uses a fixed budget, so max() would mask the difference.
        return seen[0]

    assert _run("brief") < _run("standard") < _run("deep")


def test_compose_without_a_preference_still_works() -> None:
    """Back-compat: existing jobs have output_length NULL."""
    with patch.object(ra, "get_llm_for") as mock:
        mock.return_value.invoke.return_value = MagicMock(content="<h2>Key Facts</h2>")
        out = ra.compose_report({
            "chunk_summaries": [{"facts": [{"content": "f", "video_title": "t"}]}],
            "statistics": {},
            "job_type": "topic",
            "topic": "t",
        })
    assert "Key Facts" in out["final_html"]
