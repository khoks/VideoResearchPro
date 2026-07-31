"""S-1.14.13 — selection quotas: preferred coverage + concentration cap.

Measured motivation (D-057 reference pool of 651 candidates): the rank prompt
already asks the model to prefer preferred-channel videos, and only **12 of
29** preferred channels reached the corpus — while **14 of the 18 missing
ones had candidates sitting in the rejected pool** and one NON-preferred
channel took 10.5% of the 200 picks. A prompt cannot guarantee coverage;
these tests pin the code that does.
"""
from unittest.mock import patch

from app.agents import search_agent as sa
from app.agents.search_agent import _enforce_selection_quotas


def _v(vid: str, chan: str, dur: int = 600) -> dict:
    return {
        "video_id": vid,
        "title": f"title {vid}",
        "channel_id": chan,
        "channel_name": f"name-{chan}",
        "duration_seconds": dur,
    }


def test_every_preferred_channel_with_a_candidate_gets_a_slot() -> None:
    """The headline defect: preferred channels present in the pool but absent
    from the selection."""
    # One dominant channel the ranker loved, plus 5 preferred channels it ignored.
    ranked = [_v(f"d{i}", "DOM") for i in range(10)]
    pool = ranked + [_v(f"p{i}", f"PREF{i}") for i in range(5)]
    preferred = [f"PREF{i}" for i in range(5)]

    picked, notes = _enforce_selection_quotas(ranked, pool, preferred, target=10)

    covered = {v["channel_id"] for v in picked} & set(preferred)
    assert covered == set(preferred), "every available preferred channel must appear"
    assert notes["preferred_covered"] == 5
    assert notes["preferred_available"] == 5


def test_no_channel_exceeds_the_concentration_cap() -> None:
    # Enough channel diversity that the cap CAN be honoured. (When it can't,
    # the relax pass deliberately fills the target instead of under-
    # delivering — covered separately below.)
    pool = [_v(f"d{i}", "DOM") for i in range(100)] + [
        _v(f"o{i}", f"CH{i}") for i in range(200)
    ]
    picked, notes = _enforce_selection_quotas(pool, pool, [], target=100)

    counts: dict[str, int] = {}
    for v in picked:
        counts[v["channel_id"]] = counts.get(v["channel_id"], 0) + 1
    cap = max(sa._MIN_PER_CHANNEL_CAP, int(100 * sa._MAX_CHANNEL_SHARE))
    assert counts["DOM"] <= cap
    assert notes["max_channel_count"] <= cap


def test_merit_order_is_preserved_for_the_remaining_slots() -> None:
    """Quotas reserve slots; they do not reshuffle the model's ranking."""
    ranked = [_v(f"r{i}", f"CH{i}") for i in range(10)]
    picked, _ = _enforce_selection_quotas(ranked, ranked, [], target=5)
    assert [v["video_id"] for v in picked] == ["r0", "r1", "r2", "r3", "r4"]


def test_preferred_candidates_eliminated_by_the_tournament_are_recovered() -> None:
    """Quotas draw from the FULL pool, not the post-tournament survivors — a
    preferred channel can be knocked out in an early round."""
    survivors = [_v(f"s{i}", "DOM") for i in range(5)]
    full_pool = survivors + [_v("lost", "PREF_A")]
    picked, notes = _enforce_selection_quotas(survivors, full_pool, ["PREF_A"], target=5)
    assert "lost" in {v["video_id"] for v in picked}
    assert notes["preferred_covered"] == 1


def test_target_is_always_filled_even_when_the_cap_would_starve_it() -> None:
    """Few channels available: relax the cap rather than under-deliver."""
    pool = [_v(f"d{i}", "DOM") for i in range(20)]
    picked, _ = _enforce_selection_quotas(pool, pool, [], target=15)
    assert len(picked) == 15


def test_no_duplicates_and_never_exceeds_target() -> None:
    pool = [_v(f"v{i}", f"CH{i % 7}") for i in range(60)]
    picked, _ = _enforce_selection_quotas(pool, pool, ["CH1", "CH2"], target=20)
    ids = [v["video_id"] for v in picked]
    assert len(ids) == len(set(ids)) == 20


def test_empty_inputs_are_safe() -> None:
    assert _enforce_selection_quotas([], [], [], target=10) == ([], {})
    picked, _ = _enforce_selection_quotas([_v("a", "C")], [_v("a", "C")], [], target=0)
    assert picked == []


# --- shorts filter: preferred channels are exempt --------------------------
def _keep(v: dict, preferred: set, min_dur=None, max_dur=None) -> bool:
    return sa._passes_duration_filter(v, min_dur, max_dur, preferred)[0]


def test_shorts_are_dropped_but_preferred_channels_are_exempt() -> None:
    """Filtering preferred channels too cost 6 of 29 their only candidates on
    the real pool — an explicit 'include this creator' outranks an inferred
    'prefer substantive'."""
    pref = {"PREF"}
    assert not _keep(_v("short_other", "OTHER", dur=45), pref)
    assert _keep(_v("short_pref", "PREF", dur=45), pref)
    assert _keep(_v("long_other", "OTHER", dur=900), pref)


def test_short_drop_is_reported_so_it_is_not_silent() -> None:
    keep, was_short = sa._passes_duration_filter(
        _v("s", "OTHER", dur=30), None, None, set()
    )
    assert (keep, was_short) == (False, True)
    # A user-set floor is a different reason; not counted as a Shorts drop.
    keep, was_short = sa._passes_duration_filter(
        _v("s", "OTHER", dur=30), 5, None, set()
    )
    assert (keep, was_short) == (False, False)


def test_explicit_user_duration_bounds_still_win() -> None:
    """When the user sets their own floor, we do not second-guess it."""
    assert not _keep(_v("v", "PREF", dur=60), {"PREF"}, min_dur=5)
    assert not _keep(_v("v", "OTHER", dur=9000), set(), max_dur=60)
