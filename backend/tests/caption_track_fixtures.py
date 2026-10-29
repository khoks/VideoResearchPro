"""Caption-track lists shaped like the player responses measured for S-1.11.11.

Each shape mirrors a real video from docs/notes/2026-10-25-caption-track-
choice.json (the raw measurement): the caption tracks in their listed order,
the player's audio-track ids (``<language>.4`` original, ``.10`` auto-dub),
and the Data API's ``defaultAudioLanguage``. ``old`` is what the pre-S-1.11.11
rule (``en`` / ``en-auto``, then the first listed track) ingested, so a test
can prove its fixture tells the two rules apart.

The fakes run the REAL ``youtube_transcript_api`` parsing: ``TranscriptList.
build`` over the captions JSON and ``Transcript.fetch`` over timedtext XML
served by a fake HTTP client — only the network is replaced.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse
from xml.sax.saxutils import escape

# What each track "says": the speaker's own words only in the spoken language.
TRACK_TEXT = {
    "hi": "यह वक्ता के अपने शब्द हैं और व्याख्यान हिंदी में है",
    "bn": "এটি বাংলা ভাষায় মেশিন দ্বারা ডাব করা অনুবাদ",
    "en-US": "this is the machine English dub of the lecture",
    "en": "these are the English words heard in the original audio",
    "ja": "これは日本語の吹き替えです",
    "ta": "இது தமிழ் டப்பிங்",
    "uk": "це український дубляж",
    "ar": "هذه دبلجة عربية",
    "fr-FR": "ceci est le doublage français",
}


def caption(lang: str, kind: str = "asr") -> dict:
    asr = kind == "asr"
    return {
        "baseUrl": (
            f"https://www.youtube.com/api/timedtext?v=VID&lang={lang}"
            + ("&kind=asr" if asr else "")
        ),
        "name": {"runs": [{"text": f"{lang}{' (auto-generated)' if asr else ''}"}]},
        "vssId": ("a." if asr else ".") + lang,
        "languageCode": lang,
        **({"kind": "asr"} if asr else {}),
        "isTranslatable": True,
        "trackName": "",
    }


def captions_json(tracks: list[dict], audio: list[str] | None = None) -> dict:
    indices = list(range(len(tracks)))
    if audio:
        audio_tracks = [{"captionTrackIndices": indices, "audioTrackId": a} for a in audio]
        default = next(i for i, a in enumerate(audio) if a.endswith(".4"))
    else:
        audio_tracks = [{"captionTrackIndices": indices}]
        default = 0
    return {
        "captionTracks": tracks,
        "audioTracks": audio_tracks,
        "defaultAudioTrackIndex": default,
        "translationLanguages": [],
    }


@dataclass(frozen=True)
class Shape:
    video_id: str
    tracks: tuple
    audio: tuple | None
    declared: str | None  # snippet.defaultAudioLanguage
    expect: tuple | None  # (language, kind) the new rule ingests; None = refuse
    old: str | None  # language the old rule ingested

    def captions(self) -> dict:
        return captions_json([caption(lang, kind) for lang, kind in self.tracks], list(self.audio or []) or None)


SHAPES = {
    # v6CuYULP3tM: Hindi interview, English auto-dub listed first, no
    # declared audio language. The old rule ingested the dub.
    "hindi_audio_english_dub": Shape(
        "v6CuYULP3tM", (("en-US", "asr"), ("hi", "asr")), ("hi.4", "en-US.10"),
        None, ("hi", "asr"), "en-US",
    ),
    # 1v3_AQ26jZ0: Hindi lecture, Bengali and English auto-dubs.
    "hindi_audio_bengali_and_english_dubs": Shape(
        "1v3_AQ26jZ0", (("bn", "asr"), ("en-US", "asr"), ("hi", "asr")),
        ("en-US.10", "bn.10", "hi.4"), "hi", ("hi", "asr"), "bn",
    ),
    # A Hindi video with a creator-uploaded Hindi track and an English
    # translation: the manual Hindi track wins over both.
    "manual_hindi_track": Shape(
        "manualHindi1", (("en", "manual"), ("hi", "manual"), ("hi", "asr")), None,
        "hi", ("hi", "manual"), "en",
    ),
    # J-HV7gNVdd0: one ASR track and nothing else to choose from.
    "asr_only": Shape("J-HV7gNVdd0", (("hi", "asr"),), None, "hi", ("hi", "asr"), "hi"),
    # Spoken language unknown: nothing declared, one audio track and no ASR
    # track to read the recogniser's language from. English-first is kept.
    "unknown_audio_language": Shape(
        "unknownLang1", (("en", "manual"), ("hi", "manual")), None, None, ("en", "manual"), "en",
    ),
    # 8Hdx8IGL1sc (reduced): English original, dubbed into many languages.
    "english_audio": Shape(
        "8Hdx8IGL1sc",
        (("ar", "asr"), ("bn", "asr"), ("en", "asr"), ("fr-FR", "asr"), ("hi", "asr")),
        ("fr-FR.10", "ar.10", "bn.10", "en-US.4", "hi.10"), "en-IN", ("en", "asr"), "en",
    ),
    # C6YtPJxNULA: Hindi speech, the creator's English translation listed
    # first. The old rule ingested the translation.
    "hindi_audio_english_translation": Shape(
        "C6YtPJxNULA", (("en", "manual"), ("hi", "asr")), None, "hi", ("hi", "asr"), "en",
    ),
    # C6YtPJxNULA's tracks with nothing declared (or the 1-unit lookup
    # failed): on a single-audio video the ASR track is the recogniser run on
    # the only audio, so its `hi` is the spoken language — not English-first.
    "hindi_audio_english_translation_undeclared": Shape(
        "undeclaredC6", (("en", "manual"), ("hi", "asr")), None, None, ("hi", "asr"), "en",
    ),
    # Declared `ur`, but no track is in Urdu: the original audio (`hi.4`)
    # decides, not English-first and the creator's English translation.
    "declared_language_without_track": Shape(
        "declaredUr01", (("en", "manual"), ("hi", "asr"), ("ja", "asr")),
        ("hi.4", "ja.10"), "ur", ("hi", "asr"), "en",
    ),
    # The same on a single-audio video: the ASR track's language decides.
    "declared_language_without_track_single_audio": Shape(
        "declaredUr02", (("en", "manual"), ("hi", "asr")), None, "ur", ("hi", "asr"), "en",
    ),
    # v6CuYULP3tM's shape with a wrong declaration (`en-IN`, the channel
    # default on several Hinglish podcasts): the cached `en-US` dub shares the
    # declared primary subtag, yet it is still the dub.
    "mislabelled_declaration_hides_dub": Shape(
        "enINdub0001", (("en-US", "asr"), ("hi", "asr")), ("hi.4", "en-US.10"),
        "en-IN", ("hi", "asr"), "en-US",
    ),
    # IcVYyF3EEbk: original audio `hi.4`, an `en-US.10` dub, and one ASR
    # track `en` — the original's (a dub's track carries the dub's exact code).
    "original_asr_beside_regional_dub": Shape(
        "IcVYyF3EEbk", (("en", "asr"),), ("en-US.10", "hi.4"), "en-IN", ("en", "asr"), "en",
    ),
    # IbcYNtZ8HZY: declared English, recogniser heard Hindi; three dubs.
    "dubs_beside_mislabelled_original": Shape(
        "IbcYNtZ8HZY", (("hi", "asr"), ("ja", "asr"), ("ta", "asr"), ("uk", "asr")),
        ("en-US.4", "ta.10", "ja.10", "uk.10"), "en", ("hi", "asr"), "hi",
    ),
    # Every track is a dub: refuse rather than ingest words never said.
    "only_dubs": Shape(
        "onlyDubs01", (("en-US", "asr"),), ("hi.4", "en-US.10"), "hi", None, "en-US",
    ),
}


def old_rule_language(shape: Shape) -> str | None:
    """The pre-S-1.11.11 choice: ``fetch(languages=[en, en-auto, en, en-auto])``
    (manual before generated per code), else the first listed track, manual
    tracks iterating before generated ones."""
    manual = [lang for lang, kind in shape.tracks if kind == "manual"]
    generated = [lang for lang, kind in shape.tracks if kind == "asr"]
    for code in ("en", "en-auto", "en", "en-auto"):
        if code in manual or code in generated:
            return code
    ordered = manual + generated
    return ordered[0] if ordered else None


class _Response:
    status_code = 200

    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class FakeHttp:
    """Serves timedtext XML per ``lang`` and records what was fetched."""

    def __init__(self):
        self.fetched: list[str] = []

    def get(self, url: str) -> _Response:
        lang = parse_qs(urlparse(url).query)["lang"][0]
        self.fetched.append(lang)
        text = escape(TRACK_TEXT.get(lang, f"{lang} track text"))
        return _Response(
            '<?xml version="1.0" encoding="utf-8" ?><transcript>'
            f'<text start="0.0" dur="2.5">{text}</text>'
            f'<text start="2.5" dur="2.0">{text}</text>'
            "</transcript>"
        )


class _FakeFetcher:
    def __init__(self, captions: dict):
        self._http_client = FakeHttp()
        self._captions = captions
        self.listed = 0

    def _fetch_captions_json(self, video_id: str) -> dict:
        self.listed += 1
        return self._captions


class FakeTranscriptApi:
    """Stands in for ``YouTubeTranscriptApi``: same internals the service
    reads (``_fetcher._fetch_captions_json`` and ``_fetcher._http_client``)."""

    def __init__(self, captions: dict):
        self._fetcher = _FakeFetcher(captions)

    @property
    def listed(self) -> int:
        return self._fetcher.listed

    @property
    def fetched(self) -> list[str]:
        return self._fetcher._http_client.fetched
