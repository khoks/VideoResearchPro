"""S-1.14.19: map batching, truncation and concurrency.

R1 run 6 (docs/notes/2026-10-19-map-coverage.md) showed three things these
tests pin:
- a map response cut off at the completion budget came back as
  ``{"raw": ...}``, counted as a success, and lost its whole batch;
- the map model writes a roughly fixed number of items per call, so large
  mixed batches starve late sources, and mixing sources lets one video's
  on-screen span or script leak into another's items. `source` batching
  never mixes;
- smaller batches mean more calls, so they run concurrently, with results
  kept in batch order.
"""
from __future__ import annotations

import json
import re
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.agents import report_agent
from app.config import settings


def _chunk(vid: str, i: int, words: int = 40) -> dict:
    return {
        "text": " ".join(f"{vid}word{i}x{k}" for k in range(words)),
        "metadata": {
            "video_id": vid,
            "video_title": f"Video {vid}",
            "channel_name": f"Ch{vid}",
            "video_url": f"https://www.youtube.com/watch?v={vid}",
            "timestamp_start": float(i * 60),
        },
    }


def _response(content: str, finish: str | None = None) -> MagicMock:
    r = MagicMock()
    r.content = content
    r.response_metadata = {"finish_reason": finish} if finish else {}
    return r


def _items_for(prompt: str) -> str:
    """One fact per chunk header in the prompt, tagged with its video."""
    heads = re.findall(r"\[Video (\w+) \| Ch\w+ \| (\d+:\d+)", prompt)
    facts = [{"content": f"fact {v} {ts}", "video_title": f"Video {v}", "channel_name": f"Ch{v}",
              "video_url": f"https://www.youtube.com/watch?v={v}", "timestamp_display": ts,
              "timestamp_seconds": 0, "modality": "said"} for v, ts in heads]
    return json.dumps({"facts": facts, "comments": [], "conclusions": [], "references": [], "speakers": []})


class _EchoLLM:
    """Answers every map call with one fact per chunk header; records prompts."""

    def __init__(self, delays: dict[str, float] | None = None):
        self.prompts: list[str] = []
        self.delays = delays or {}
        self._lock = threading.Lock()

    def invoke(self, messages):
        prompt = messages[0].content
        with self._lock:
            self.prompts.append(prompt)
        first = re.search(r"\[Video (\w+) \|", prompt)
        if first and first.group(1) in self.delays:
            time.sleep(self.delays[first.group(1)])
        return _response(_items_for(prompt))


def _videos_per_call(prompts: list[str]) -> list[set[str]]:
    return [set(re.findall(r"\[Video (\w+) \|", p)) for p in prompts]


@pytest.fixture
def small_batches(monkeypatch):
    # Three formatted chunks per batch (one measures 220 tokens), whatever
    # the model's window.
    monkeypatch.setattr(settings, "REPORT_MAP_BATCH_TOKENS", 700)


def _run(chunks, llm):
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        return report_agent.map_chunks({"job_type": "topic", "topic": "t", "transcript_chunks": chunks})


# ---------- batching ----------------------------------------------------------

def test_packed_batching_mixes_sources_up_to_the_cap(small_batches, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "packed")
    chunks = [_chunk("a", 0), _chunk("a", 1), _chunk("b", 0), _chunk("b", 1), _chunk("c", 0)]
    llm = _EchoLLM()
    out = _run(chunks, llm)
    calls = _videos_per_call(llm.prompts)
    assert any(len(c) > 1 for c in calls), "packed mode should put two sources in one call here"
    assert out["processing_notes"]["map_batching"] == "packed"


def test_source_batching_never_puts_two_sources_in_one_call(small_batches, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "source")
    chunks = [_chunk("a", 0), _chunk("a", 1), _chunk("b", 0), _chunk("c", 0), _chunk("c", 1)]
    llm = _EchoLLM()
    out = _run(chunks, llm)
    calls = _videos_per_call(llm.prompts)
    assert [len(c) for c in calls] == [1, 1, 1]
    assert [c.pop() for c in calls] == ["a", "b", "c"]
    assert out["processing_notes"]["map_batches"] == 3


def test_a_source_larger_than_the_cap_splits_into_batches_of_its_own(small_batches, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "source")
    chunks = [_chunk("a", i) for i in range(7)] + [_chunk("b", 0)]
    llm = _EchoLLM()
    _run(chunks, llm)
    calls = _videos_per_call(llm.prompts)
    assert len(calls) >= 3
    assert all(c == {"a"} for c in calls[:-1]) and calls[-1] == {"b"}


def test_an_unknown_batching_mode_falls_back_to_packed(small_batches, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "by-vibes")
    out = _run([_chunk("a", 0)], _EchoLLM())
    assert out["processing_notes"]["map_batching"] == "packed"


def test_each_call_gets_a_budget_sized_to_its_own_batch(monkeypatch):
    # A one-chunk batch reserves 4,096 tokens, not the whole 30K cap: what a
    # call reserves against a rate limit tracks what it can write.
    monkeypatch.setattr(settings, "REPORT_MAP_BATCH_TOKENS", 30_000)
    with patch.object(report_agent, "get_llm_for", return_value=_EchoLLM()) as get_llm:
        report_agent.map_chunks({"job_type": "topic", "topic": "t", "transcript_chunks": [_chunk("a", 0)]})
    assert get_llm.call_args.kwargs["max_tokens"] == 4_096


@pytest.mark.parametrize("batch_tokens,cap,expected", [
    (220, 30_000, 4_096),        # floor, rounded to the step
    (20_000, 30_000, 20_480),    # ratio 1.0, rounded up to a 4,096 step
    (29_000, 30_000, 30_000),    # never above the cap
    (9_000, 4_096, 4_096),       # a small output ceiling wins
])
def test_map_call_budget(batch_tokens, cap, expected):
    assert report_agent._map_call_budget(batch_tokens, cap) == expected


def test_the_window_still_caps_a_larger_setting(monkeypatch):
    monkeypatch.setattr(settings, "REPORT_MAP_BATCH_TOKENS", 10**9)
    out = _run([_chunk("a", 0)], _EchoLLM())
    assert out["processing_notes"]["map_batch_tokens"] == report_agent._batch_budget("report_map_chunks")


# ---------- truncation --------------------------------------------------------

@pytest.mark.parametrize("meta", [
    {"finish_reason": "length"},          # OpenAI
    {"stop_reason": "max_tokens"},        # Anthropic
    {"finish_reason": "MAX_TOKENS"},      # Google
])
def test_every_provider_spelling_of_out_of_budget_is_recognised(meta):
    r = MagicMock()
    r.response_metadata = meta
    assert report_agent._stopped_for_length(r)


def test_ordinary_stops_and_missing_metadata_are_not_truncation():
    r = MagicMock()
    r.response_metadata = {"finish_reason": "stop"}
    assert not report_agent._stopped_for_length(r)
    assert not report_agent._stopped_for_length(MagicMock())   # metadata not a dict
    assert not report_agent._stopped_for_length(object())


def test_a_truncated_batch_is_retried_in_halves_not_returned_raw(small_batches):
    chunks = [_chunk("a", 0), _chunk("a", 1)]

    class _TruncatesFullBatch(_EchoLLM):
        def invoke(self, messages):
            prompt = messages[0].content
            self.prompts.append(prompt)
            if len(re.findall(r"\[Video ", prompt)) > 1:
                return _response('{"facts": [{"content": "cut off', finish="length")
            return _response(_items_for(prompt))

    llm = _TruncatesFullBatch()
    out = _run(chunks, llm)
    assert len(llm.prompts) == 3                      # full batch, then two halves
    assert all("raw" not in s for s in out["chunk_summaries"])
    assert sum(len(s["facts"]) for s in out["chunk_summaries"]) == 2
    assert out["processing_notes"]["map_batches_failed"] == 0


def test_a_length_stop_is_a_failure_even_when_the_json_happens_to_close(small_batches):
    # The model wanted to write more: whatever it did not reach is lost
    # unless the batch is re-run in halves.
    chunks = [_chunk("a", 0), _chunk("a", 1)]

    class _ClosesButCut(_EchoLLM):
        def invoke(self, messages):
            prompt = messages[0].content
            self.prompts.append(prompt)
            finish = "length" if len(re.findall(r"\[Video ", prompt)) > 1 else None
            return _response(_items_for(prompt), finish=finish)

    llm = _ClosesButCut()
    out = _run(chunks, llm)
    assert len(llm.prompts) == 3
    assert [len(s["facts"]) for s in out["chunk_summaries"]] == [1, 1]


def test_fenced_json_is_accepted_and_a_bare_list_is_not():
    assert report_agent._parse_map_json('```json\n{"facts": []}\n```') == {"facts": []}
    with pytest.raises(report_agent.MapOutputError):
        report_agent._parse_map_json("[1, 2]")
    with pytest.raises(report_agent.MapOutputError):
        report_agent._parse_map_json('{"facts": [')


# ---------- concurrency -------------------------------------------------------

def test_concurrent_batches_keep_batch_order_and_merge_counts(small_batches, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "source")
    monkeypatch.setattr(settings, "REPORT_MAP_CONCURRENCY", 4)
    vids = ["a", "b", "c", "d"]
    chunks = [_chunk(v, i) for v in vids for i in range(2)]
    # Later batches finish FIRST.
    llm = _EchoLLM(delays={"a": 0.15, "b": 0.10, "c": 0.05, "d": 0.0})
    out = _run(chunks, llm)
    order = [s["facts"][0]["content"].split()[1] for s in out["chunk_summaries"]]
    assert order == vids
    assert [r["batch_index"] for r in out["map_batch_records"]] == [0, 1, 2, 3]
    assert out["processing_notes"]["map_modality"] == {"said": 8}


# ---------- review fixes (S-1.14.19) ------------------------------------------

def test_a_rate_limit_is_retried_with_backoff_before_any_bisect(small_batches, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "source")
    calls = {"n": 0}

    class _RateLimitedOnce(_EchoLLM):
        def invoke(self, messages):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("Error code: 429 - Rate limit reached for gpt-5.6-luna")
            return super().invoke(messages)

    llm = _RateLimitedOnce()
    with patch.object(report_agent.time, "sleep") as sleep:
        out = _run([_chunk("a", 0), _chunk("a", 1)], llm)
    assert sleep.call_count == 1
    assert len(llm.prompts) == 1                        # the same whole batch, not halves
    assert [len(s["facts"]) for s in out["chunk_summaries"]] == [2]
    assert out["processing_notes"]["map_batches_failed"] == 0


def test_a_small_output_ceiling_shrinks_batches_and_halves_until_output_fits(monkeypatch):
    # The 4,096-token default ceiling of any model without a measured one:
    # batches are capped at 1.5x it, and a still-truncated batch keeps
    # halving, so no content is lost (it used to fail in both halves).
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "packed")
    monkeypatch.setattr(settings, "REPORT_MAP_BATCH_TOKENS", 120_000)
    monkeypatch.setattr(report_agent, "max_output_for", lambda model: 4_096)
    chunks = [_chunk("a", i) for i in range(40)]

    class _WritesTooMuch(_EchoLLM):
        def invoke(self, messages):
            prompt = messages[0].content
            self.prompts.append(prompt)
            if len(re.findall(r"\[Video ", prompt)) > 6:      # pretend output would exceed the ceiling
                return _response('{"facts": [', finish="length")
            return _response(_items_for(prompt))

    llm = _WritesTooMuch()
    out = _run(chunks, llm)
    notes = out["processing_notes"]
    assert notes["map_batch_tokens"] == 6_144
    assert notes["map_chunks_dropped"] == 0 and notes["map_batches_failed"] == 0
    assert sum(len(s["facts"]) for s in out["chunk_summaries"]) == 40


def test_concurrency_really_overlaps_calls(small_batches, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "source")
    monkeypatch.setattr(settings, "REPORT_MAP_CONCURRENCY", 4)
    state = {"now": 0, "peak": 0}
    lock = threading.Lock()

    class _Counting(_EchoLLM):
        def invoke(self, messages):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            try:
                return super().invoke(messages)
            finally:
                with lock:
                    state["now"] -= 1

    _run([_chunk(v, 0) for v in "abcd"], _Counting())
    assert state["peak"] >= 2


def test_shared_source_text_gives_the_same_verdicts_under_threads(monkeypatch):
    # Concurrent map batches share one VideoText per source; its cached
    # SequenceMatcher used to interleave set_seq1/find_longest_match across
    # threads. A tiny switch interval makes that interleaving near-certain.
    import sys
    from concurrent.futures import ThreadPoolExecutor

    from app.services import quote_fidelity as qf

    speech = " ".join(f"word{i} token{i * 7 % 13} phrase{i % 5}" for i in range(300))
    video = qf.VideoText.from_raw("t", speech)
    words = qf.normalise(speech).split()
    pieces = [" ".join(words[k:k + 3 + k % 9]) for k in range(0, 800, 7)]
    expected = [qf.VideoText.from_raw("t", speech)._anchor(p) for p in pieces]
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            got = list(pool.map(video._anchor, pieces * 20))
    finally:
        sys.setswitchinterval(old)
    assert got == expected * 20


# ---------- starved-source re-map (S-1.14.20) ---------------------------------

class _FirstSourceOnly(_EchoLLM):
    """Extracts only the FIRST video in each prompt: the starvation a large
    packed batch produced for late sources in R1 runs 5-7."""

    def invoke(self, messages):
        prompt = messages[0].content
        self.prompts.append(prompt)
        first = re.search(r"\[Video (\w+) \|", prompt).group(1)
        kept = "\n".join(line for line in prompt.splitlines()
                         if not line.startswith("[Video ") or line.startswith(f"[Video {first} |"))
        return _response(_items_for(kept))


def _two_sources(n_a=12, n_b=12):
    return [_chunk("a", i) for i in range(n_a)] + [_chunk("b", i) for i in range(n_b)]


def test_a_starved_source_is_remapped_alone_and_replaces_its_thin_items(monkeypatch):
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "packed")
    monkeypatch.setattr(settings, "REPORT_MAP_BATCH_TOKENS", 6_000)      # both sources in one call
    llm = _FirstSourceOnly()
    out = _run(_two_sources(), llm)
    calls = _videos_per_call(llm.prompts)
    assert calls[0] == {"a", "b"} and calls[1:] == [{"b"}]
    facts = [f["content"].split()[1] for s in out["chunk_summaries"] for f in s["facts"]]
    assert facts.count("a") == 12 and facts.count("b") == 12
    notes = out["processing_notes"]
    assert (notes["map_batches"], notes["map_sources_remapped"], notes["map_remap_calls"]) == (1, 1, 1)
    assert [r["batch_index"] for r in out["map_batch_records"]] == [0, 1]


def test_a_small_source_is_not_called_starved(monkeypatch):
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "packed")
    monkeypatch.setattr(settings, "REPORT_MAP_BATCH_TOKENS", 6_000)
    llm = _FirstSourceOnly()
    out = _run(_two_sources(n_b=5), llm)                             # 5 chunks: under the floor
    assert len(llm.prompts) == 1
    assert out["processing_notes"]["map_sources_remapped"] == 0


def test_source_batching_never_remaps(monkeypatch, small_batches):
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "source")
    llm = _FirstSourceOnly()
    out = _run(_two_sources(), llm)
    assert all(len(c) == 1 for c in _videos_per_call(llm.prompts))
    assert out["processing_notes"]["map_sources_remapped"] == 0


def test_starvation_is_judged_on_density_not_presence(monkeypatch):
    # A source with a token item or two is still starved at 24 chunks.
    monkeypatch.setattr(settings, "REPORT_MAP_BATCHING", "packed")
    monkeypatch.setattr(settings, "REPORT_MAP_BATCH_TOKENS", 9_000)

    class _OneItemForB(_FirstSourceOnly):
        def invoke(self, messages):
            r = super().invoke(messages)
            body = json.loads(r.content)
            if "[Video b |" in messages[0].content and len(_videos_per_call([messages[0].content])[0]) > 1:
                body["facts"].append({"content": "fact b 0:00", "video_title": "Video b", "channel_name": "Chb",
                                      "video_url": "https://www.youtube.com/watch?v=b", "timestamp_display": "0:00",
                                      "timestamp_seconds": 0, "modality": "said"})
            return _response(json.dumps(body))

    out = _run(_two_sources(n_b=24), _OneItemForB())
    assert out["processing_notes"]["map_sources_remapped"] == 1
    # The token item from the starved pass is replaced, not kept beside the re-map.
    facts = [f["content"] for s in out["chunk_summaries"] for f in s["facts"]]
    assert sum(1 for f in facts if f.split()[1] == "b") == 24
