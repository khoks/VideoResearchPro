"""S-1.11.11: the caption track is the one in the video's spoken language,
never an auto-dub or a translation.

Fixtures are the shapes measured on the library's Hindi / Hinglish videos
(tests/caption_track_fixtures.py). Every assertion runs the production
`fetch_transcript` path with only the network replaced, and the fixtures are
checked to FAIL under the old English-first rule — otherwise a test that
passes would prove nothing.
"""
from __future__ import annotations

import pytest
from youtube_transcript_api import YouTubeTranscriptApi

from app.services import youtube_service
from tests.caption_track_fixtures import SHAPES, TRACK_TEXT, FakeTranscriptApi, old_rule_language


class _NoWait:
    def wait(self) -> None:
        return None


@pytest.fixture
def harness(monkeypatch):
    """Run `fetch_transcript` against one shape; record Data API lookups,
    cache writes and Whisper calls."""
    state = {"lookups": [], "saved": [], "whisper": 0, "api": None}

    def run(shape, *, allow_whisper=False, **kwargs):
        api = FakeTranscriptApi(shape.captions())
        state["api"] = api
        monkeypatch.setattr(youtube_service, "_build_transcript_api", lambda: api)

        def lookup(ids, job_id=""):
            state["lookups"].append(list(ids))
            return {vid: shape.declared for vid in ids}

        monkeypatch.setattr(youtube_service, "get_default_audio_languages", lookup)
        return youtube_service.fetch_transcript(
            shape.video_id, language="en", allow_whisper=allow_whisper, **kwargs
        )

    monkeypatch.setattr(youtube_service, "transcript_limiter", _NoWait())
    monkeypatch.setattr(youtube_service, "transcript_breaker", youtube_service._TranscriptCircuitBreaker())
    monkeypatch.setattr(youtube_service, "_load_from_cache", lambda vid, tag: None)
    monkeypatch.setattr(
        youtube_service, "_save_to_cache",
        lambda vid, seg, lang, src, tag: state["saved"].append((vid, lang, src)),
    )
    monkeypatch.setattr(youtube_service.time, "sleep", lambda s: None)

    def whisper(video_id, job_id=""):
        state["whisper"] += 1
        return None

    monkeypatch.setattr(youtube_service, "_transcribe_with_whisper", whisper)
    state["run"] = run
    return state


CHOSEN = [name for name, s in SHAPES.items() if s.expect is not None]


@pytest.mark.parametrize("name", CHOSEN)
def test_fetch_transcript_ingests_the_spoken_language_track(harness, name):
    shape = SHAPES[name]
    result = harness["run"](shape)

    assert result is not None
    language, kind = shape.expect
    assert result.language == language
    assert result.source == "youtube"
    assert result.track["language"] == language
    assert result.track["kind"] == kind
    # The words are the chosen track's, and only that track was downloaded.
    assert result.segments[0]["text"] == TRACK_TEXT[language]
    assert harness["api"].fetched == [language]
    assert harness["saved"] == [(shape.video_id, language, "youtube")]


@pytest.mark.parametrize(
    "name",
    [
        "hindi_audio_english_dub",
        "hindi_audio_bengali_and_english_dubs",
        "manual_hindi_track",
        "hindi_audio_english_translation",
        "only_dubs",
    ],
)
def test_fixture_fails_under_the_old_english_first_rule(name):
    """The shapes the story is about must disagree with the old rule, or the
    test above could pass on the bug."""
    shape = SHAPES[name]
    expected = shape.expect[0] if shape.expect else None
    assert old_rule_language(shape) == shape.old
    assert shape.old != expected


def test_auto_dubs_are_reported_as_skipped(harness):
    result = harness["run"](SHAPES["hindi_audio_bengali_and_english_dubs"])
    assert result.track["skipped_dubbed"] == ["bn", "en-US"]
    assert result.track["match"] == "spoken"


def test_spoken_language_comes_from_the_player_when_none_is_declared(harness):
    """v6CuYULP3tM declares no audio language; the original audio track
    (`hi.4`) is the only signal, and it costs no quota."""
    result = harness["run"](SHAPES["hindi_audio_english_dub"])
    assert result.track["spoken_language"] == "hi"
    assert result.track["spoken_language_source"] == "player"


def test_declared_language_is_looked_up_only_when_the_tracks_offer_a_choice(harness):
    harness["run"](SHAPES["asr_only"])
    harness["run"](SHAPES["hindi_audio_english_dub"])  # one language left after the dub
    assert harness["lookups"] == []

    result = harness["run"](SHAPES["hindi_audio_english_translation"])
    assert harness["lookups"] == [["C6YtPJxNULA"]]
    assert result.track["spoken_language"] == "hi"
    assert result.track["spoken_language_source"] == "data_api"


def test_a_caller_supplied_audio_language_skips_the_lookup(harness):
    result = harness["run"](SHAPES["hindi_audio_english_translation"], audio_language="hi")
    assert harness["lookups"] == []
    assert result.language == "hi"


def test_a_caller_that_found_no_declaration_gets_the_english_first_fallback(harness):
    result = harness["run"](SHAPES["hindi_audio_english_translation"], audio_language=None)
    assert harness["lookups"] == []
    assert (result.language, result.track["match"]) == ("en", "fallback_english_first")


def test_unknown_spoken_language_keeps_english_first(harness):
    result = harness["run"](SHAPES["unknown_audio_language"])
    assert harness["lookups"] == [["unknownLang1"]]
    assert result.track["spoken_language"] is None
    assert result.track["match"] == "fallback_english_first"


def test_failed_lookup_falls_back_instead_of_failing(harness, monkeypatch):
    shape = SHAPES["hindi_audio_english_translation"]
    api = FakeTranscriptApi(shape.captions())
    monkeypatch.setattr(youtube_service, "_build_transcript_api", lambda: api)

    def boom(ids, job_id=""):
        raise youtube_service.QuotaExceededError("quota")

    monkeypatch.setattr(youtube_service, "get_default_audio_languages", boom)
    result = youtube_service.fetch_transcript(shape.video_id, allow_whisper=False)
    assert result is not None and result.language == "en"


def test_only_dubs_is_refused_without_retrying(harness):
    """Every track is a dub: no retries (the answer will not change in 2-8 s)
    and no dub ingested; Whisper, which hears the original, is next."""
    assert harness["run"](SHAPES["only_dubs"]) is None
    assert harness["api"].listed == 1
    assert harness["api"].fetched == []
    assert harness["saved"] == []
    assert harness["whisper"] == 0  # allow_whisper=False

    assert harness["run"](SHAPES["only_dubs"], allow_whisper=True) is None
    assert harness["whisper"] == 1


def test_regional_english_counts_as_the_spoken_language_unless_it_is_a_dub():
    """T-1.11.11.1: `en-US` matches English speech, but an `en-US` ASR track
    in a dubbed language is the dub."""
    from types import SimpleNamespace as T

    en_us = T(language_code="en-US", is_generated=True)
    hi = T(language_code="hi", is_generated=True)
    track, match, _ = youtube_service.choose_caption_track([hi, en_us], spoken_language="en-IN")
    assert (track, match) == (en_us, "spoken")

    track, match, skipped = youtube_service.choose_caption_track(
        [en_us, hi], spoken_language="hi", dubbed=frozenset({"en-us"})
    )
    assert (track, match, skipped) == (hi, "spoken", ("en-US",))


def test_dub_matching_is_on_the_exact_code():
    """IcVYyF3EEbk: an `en-US` dub must not disqualify the original's `en`
    ASR track (matching on the primary subtag would leave nothing)."""
    audio = youtube_service.audio_tracks_from_captions(
        {"audioTracks": [{"audioTrackId": "en-US.10"}, {"audioTrackId": "hi.4"}]}
    )
    assert audio.original == "hi"
    assert audio.dubbed == frozenset({"en-us"})


def test_original_audio_falls_back_to_the_default_track():
    audio = youtube_service.audio_tracks_from_captions(
        {
            "audioTracks": [{"audioTrackId": "en.3"}, {"audioTrackId": "hi.3"}],
            "defaultAudioTrackIndex": 1,
        }
    )
    assert audio.original == "hi" and audio.dubbed == frozenset({"en"})
    assert youtube_service.audio_tracks_from_captions({"audioTracks": [{"captionTrackIndices": [0]}]}) is None


def test_cache_hits_and_whisper_results_carry_no_track(monkeypatch):
    monkeypatch.setattr(
        youtube_service, "_load_from_cache", lambda vid, tag: ([{"text": "x"}], "hi", "youtube")
    )
    result = youtube_service.fetch_transcript("cached01")
    assert result == ([{"text": "x"}], "hi", "youtube", None)
    assert result.track is None


def test_library_internals_the_service_reads_still_exist():
    """`_list_caption_tracks` reads the player JSON through these. If an
    upgrade of youtube-transcript-api moves them, dub detection silently
    degrades — so fail here instead."""
    api = YouTubeTranscriptApi()
    assert callable(getattr(api._fetcher, "_fetch_captions_json", None))
    assert api._fetcher._http_client is not None


def test_missing_internals_fall_back_to_the_public_list():
    shape = SHAPES["hindi_audio_english_dub"]
    inner = FakeTranscriptApi(shape.captions())
    from youtube_transcript_api import TranscriptList

    class PublicOnly:
        def list(self, video_id):
            return TranscriptList.build(inner._fetcher._http_client, video_id, shape.captions())

    tracks, audio = youtube_service._list_caption_tracks(PublicOnly(), shape.video_id)
    assert [t.language_code for t in tracks] == ["en-US", "hi"]
    assert audio is None
