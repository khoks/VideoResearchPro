"""Echo share processing, part 2 (S-3.7.2): images, recordings, PDFs.

Remote readers are patched: the vision model (``echo_media.ocr_vision``) and
Whisper (``echo_media.transcribe`` or the Whisper call inside it). The suite
runs with ``ECHO_REMOTE_MEDIA`` off (conftest), so a test that wants a remote
reader turns it on and patches the call. On-device OCR is patched except in
one test that runs the real engine; ffmpeg and PyMuPDF run for real where a
test needs them, and a test that needs ffmpeg skips without it.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.models.share import Share
from app.models.user_llm_override import UserLLMOverride
from app.services import auth_service, echo_media, echo_processing_service, echo_vectors
from app.services.echo_media import MediaError, OcrResult, Transcript
from app.services.llm_routing import USE_CASE_REGISTRY

SHARES = "/api/v1/echo/shares"
HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is not installed")


def _studio(db, email):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield client
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


@pytest.fixture
def two(db, tmp_path, monkeypatch, chroma):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    a, ha = _studio(db, "media-a@example.com")
    b, hb = _studio(db, "media-b@example.com")
    return {"a": a, "ha": ha, "b": b, "hb": hb}


@pytest.fixture
def remote_on(monkeypatch):
    monkeypatch.setattr(settings, "ECHO_REMOTE_MEDIA", True)


def _png(text: str = "Tariffs are a tax on consumers.", size=(640, 120)) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", size, "white")
    try:
        font = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(img).text((16, 40), text, font=font, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _wav(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x10" * int(16000 * seconds))
    return buf.getvalue()


def _pdf(pages: list[str]) -> bytes:
    import fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _upload(client, headers, name, data, mime, **form):
    r = client.post(f"{SHARES}/upload", headers=headers, files={"file": (name, data, mime)},
                    data={k: str(v).lower() if isinstance(v, bool) else v for k, v in form.items()})
    assert r.status_code == 201, r.text
    return r.json()


def _process(db, share_id):
    return echo_processing_service.process_share(db, share_id)


def _get(client, headers, sid):
    return client.get(f"{SHARES}/{sid}", headers=headers).json()


def _vector(chroma, share_id):
    col = chroma.get_or_create_collection(settings.CHROMA_SHARES_COLLECTION_NAME)
    got = col.get(ids=[echo_vectors.share_vector_id(share_id)], include=["documents", "metadatas"])
    return (got["documents"] or [None])[0], (got["metadatas"] or [None])[0]


def _make_local_only(db, user_id, *, except_use_case="echo_share_ocr"):
    for uc in USE_CASE_REGISTRY:
        if uc != except_use_case:
            db.add(UserLLMOverride(user_id=user_id, use_case=uc, provider="local",
                                   model="qwen/qwen3-9b", reasoning="off"))
    db.commit()


CONFIDENT = OcrResult(text="Tariffs are a tax paid by importers, not exporters.", mean_score=0.98, boxes=2)
SHAKY = OcrResult(text="3R 3eaT f 1", mean_score=0.69, boxes=3)
NOTHING = OcrResult(text="", mean_score=0.0, boxes=0)
HINDI = "अहिंसा परमो धर्मः।\nसत्य और अहिंसा जीवन के मूल सिद्धांत हैं।"


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def test_confident_on_device_ocr_never_calls_a_vision_model(unauthenticated_client, db, two, chroma, remote_on):
    s = _upload(unauthenticated_client, two["ha"], "tweet.png", _png(), "image/png")
    with patch.object(echo_media, "ocr_local", return_value=CONFIDENT), \
            patch.object(echo_media, "ocr_vision") as vision:
        assert _process(db, s["id"]).state == "processed"
    vision.assert_not_called()
    got = _get(unauthenticated_client, two["ha"], s["id"])
    assert got["extracted_text"] == CONFIDENT.text
    assert got["processing"]["extractor"] == "ocr_local" and got["processing"]["ocr_confidence"] == 0.98
    assert got["processing"]["embedded"] is True and got["processing"]["note"] is None
    doc, meta = _vector(chroma, s["id"])
    assert "paid by importers" in doc and meta["tenant_id"] == two["a"].id and meta["content_type"] == "image"


def test_a_shaky_reading_goes_to_the_vision_model_for_the_sharers_tenant(unauthenticated_client, db, two, chroma, remote_on):
    s = _upload(unauthenticated_client, two["ha"], "quote.jpg", _png(), "image/jpeg")
    with patch.object(echo_media, "ocr_local", return_value=SHAKY), \
            patch.object(echo_media, "ocr_vision", return_value=HINDI) as vision:
        assert _process(db, s["id"]).state == "processed"
    assert vision.call_count == 1 and vision.call_args.kwargs["tenant_id"] == two["a"].id
    got = _get(unauthenticated_client, two["ha"], s["id"])
    assert got["extracted_text"] == HINDI
    assert got["processing"]["extractor"] == "ocr_vision" and got["processing"]["ocr_confidence"] == 0.69
    assert "अहिंसा" in _vector(chroma, s["id"])[0]


def test_too_little_text_also_goes_to_the_vision_model(db, two, chroma, remote_on, unauthenticated_client):
    s = _upload(unauthenticated_client, two["ha"], "sign.png", _png(), "image/png")
    tiny = OcrResult(text="EXIT", mean_score=0.99, boxes=1)
    with patch.object(echo_media, "ocr_local", return_value=tiny), \
            patch.object(echo_media, "ocr_vision", return_value="EXIT\nEmergency only") as vision:
        _process(db, s["id"])
    vision.assert_called_once()
    assert db.get(Share, s["id"]).extracted_text == "EXIT\nEmergency only"


def test_remote_media_off_keeps_images_on_device(unauthenticated_client, db, two, chroma):
    assert settings.ECHO_REMOTE_MEDIA is False  # the suite's default
    shaky = _upload(unauthenticated_client, two["ha"], "a.png", _png(), "image/png")
    blank = _upload(unauthenticated_client, two["ha"], "b.png", _png(""), "image/png")
    with patch.object(echo_media, "ocr_vision") as vision:
        with patch.object(echo_media, "ocr_local", return_value=SHAKY):
            assert _process(db, shaky["id"]).state == "processed"
        with patch.object(echo_media, "ocr_local", return_value=NOTHING):
            result = _process(db, blank["id"])
    vision.assert_not_called()
    got = _get(unauthenticated_client, two["ha"], shaky["id"])
    assert got["extracted_text"] == SHAKY.text and "ECHO_REMOTE_MEDIA" in got["processing"]["note"]
    assert result.state == "skipped" and "ECHO_REMOTE_MEDIA" in result.reason
    assert _get(unauthenticated_client, two["ha"], blank["id"])["processing_state"] == "skipped"


def test_a_local_only_tenant_is_never_sent_to_a_remote_vision_model(unauthenticated_client, db, two, chroma, remote_on):
    """Tenant A runs every model locally; tenant B uses the defaults. Only B's
    image may reach the (remote) vision model."""
    _make_local_only(db, two["a"].id)
    mine = _upload(unauthenticated_client, two["ha"], "a.png", _png(), "image/png")
    theirs = _upload(unauthenticated_client, two["hb"], "b.png", _png(), "image/png")
    with patch.object(echo_media, "ocr_local", return_value=NOTHING), \
            patch.object(echo_media, "ocr_vision", return_value="their text") as vision:
        mine_result = _process(db, mine["id"])
        theirs_result = _process(db, theirs["id"])
    assert mine_result.state == "skipped" and "runs locally" in mine_result.reason
    assert theirs_result.state == "processed"
    assert [c.kwargs["tenant_id"] for c in vision.call_args_list] == [two["b"].id]


def test_a_local_vision_model_reads_even_with_remote_media_off(unauthenticated_client, db, two, chroma):
    db.add(UserLLMOverride(user_id=two["a"].id, use_case="echo_share_ocr", provider="local",
                           model="qwen/qwen2.5-vl-7b", reasoning="off"))
    db.commit()
    s = _upload(unauthenticated_client, two["ha"], "a.png", _png(), "image/png")
    with patch.object(echo_media, "ocr_local", return_value=SHAKY), \
            patch.object(echo_media, "ocr_vision", return_value="read locally") as vision:
        assert _process(db, s["id"]).state == "processed"
    vision.assert_called_once()
    assert db.get(Share, s["id"]).extracted_text == "read locally"


def test_a_vision_failure_keeps_the_local_reading_or_fails_with_retry(unauthenticated_client, db, two, chroma, remote_on):
    shaky = _upload(unauthenticated_client, two["ha"], "a.png", _png(), "image/png")
    blank = _upload(unauthenticated_client, two["ha"], "b.png", _png(), "image/png")
    boom = RuntimeError("provider down")
    with patch.object(echo_media, "ocr_vision", side_effect=boom):
        with patch.object(echo_media, "ocr_local", return_value=SHAKY):
            assert _process(db, shaky["id"]).state == "processed"
        with patch.object(echo_media, "ocr_local", return_value=NOTHING):
            failed = _process(db, blank["id"])
    assert "could not be reached" in _get(unauthenticated_client, two["ha"], shaky["id"])["processing"]["note"]
    assert failed.state == "failed" and "vision model could not be reached" in failed.reason

    # Retry once the provider is back: the reading replaces the failure.
    with patch.object(echo_media, "ocr_local", return_value=NOTHING), \
            patch.object(echo_media, "ocr_vision", return_value="Recovered text from the image."):
        assert _process(db, blank["id"]).state == "processed"
    got = _get(unauthenticated_client, two["ha"], blank["id"])
    assert got["processing"]["error"] is None and got["extracted_text"] == "Recovered text from the image."


def test_an_image_with_nothing_to_read_has_no_vector(unauthenticated_client, db, two, chroma, remote_on):
    bare = _upload(unauthenticated_client, two["ha"], "sunset.jpg", _png(""), "image/jpeg")
    noted = _upload(unauthenticated_client, two["ha"], "sunset2.jpg", _png(""), "image/jpeg",
                    annotation="Goa, the evening we decided to move")
    with patch.object(echo_media, "ocr_local", return_value=NOTHING), \
            patch.object(echo_media, "ocr_vision", return_value=""):
        _process(db, bare["id"])
        _process(db, noted["id"])
    got = _get(unauthenticated_client, two["ha"], bare["id"])
    assert got["processing_state"] == "processed" and got["processing"]["embedded"] is False
    assert got["processing"]["note"] == "No text found in this image."
    assert _vector(chroma, bare["id"]) == (None, None)
    assert "decided to move" in _vector(chroma, noted["id"])[0]


def test_a_rerun_with_nothing_to_read_removes_the_old_vector(unauthenticated_client, db, two, chroma, remote_on):
    s = _upload(unauthenticated_client, two["ha"], "a.png", _png(), "image/png")
    with patch.object(echo_media, "ocr_local", return_value=CONFIDENT):
        _process(db, s["id"])
    assert _vector(chroma, s["id"])[0]
    with patch.object(echo_media, "ocr_local", return_value=NOTHING), \
            patch.object(echo_media, "ocr_vision", return_value=""):
        _process(db, s["id"])
    assert _vector(chroma, s["id"]) == (None, None)
    assert db.get(Share, s["id"]).embedding_id is None


def test_a_rerun_clears_what_the_last_run_derived(unauthenticated_client, db, two, chroma, remote_on):
    s = _upload(unauthenticated_client, two["ha"], "a.png", _png(), "image/png")
    with patch.object(echo_media, "ocr_local", return_value=SHAKY), \
            patch.object(echo_media, "ocr_vision", side_effect=RuntimeError("down")):
        _process(db, s["id"])
    assert _get(unauthenticated_client, two["ha"], s["id"])["processing"]["note"]
    with patch.object(echo_media, "ocr_local", return_value=CONFIDENT):
        _process(db, s["id"])
    p = _get(unauthenticated_client, two["ha"], s["id"])["processing"]
    assert p["note"] is None and p["extractor"] == "ocr_local" and p["ocr_confidence"] == 0.98


def test_an_unreadable_image_fails_with_a_reason(unauthenticated_client, db, two, chroma):
    s = _upload(unauthenticated_client, two["ha"], "broken.png", b"\x89PNG not really", "image/png")
    result = _process(db, s["id"])
    assert result.state == "failed" and "could not be read" in result.reason


def test_ocr_vision_sends_the_image_and_reads_no_text_as_empty():
    from PIL import Image

    fake = MagicMock()
    fake.invoke.return_value = SimpleNamespace(content="NO_TEXT")
    with patch("app.services.llm_service.get_llm_for", return_value=fake) as get_llm:
        assert echo_media.ocr_vision(Image.new("RGB", (4000, 1000), "white"), tenant_id="t-1", db="DB") == ""
    args, kwargs = get_llm.call_args
    assert args[0] == "echo_share_ocr" and kwargs["tenant_id"] == "t-1" and kwargs["db"] == "DB"
    content = fake.invoke.call_args.args[0][0].content
    assert "original script" in content[0]["text"]
    url = content[1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")

    import base64

    sent = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(sent.size) == settings.ECHO_OCR_VISION_MAX_SIDE  # downscaled before sending

    fake.invoke.return_value = SimpleNamespace(content=f"  {HINDI}  ")
    with patch("app.services.llm_service.get_llm_for", return_value=fake):
        assert echo_media.ocr_vision(Image.new("RGB", (10, 10)), tenant_id="t-1", db=None) == HINDI


def test_real_on_device_ocr_reads_a_rendered_line():
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import Image

    image = Image.open(io.BytesIO(_png("Tariffs are a tax on consumers", size=(900, 200)))).convert("RGB")
    got = echo_media.ocr_local(image)
    assert got is not None and got.boxes >= 1
    assert "tariffs" in got.text.lower() and got.mean_score > 0.8


# ---------------------------------------------------------------------------
# Recordings
# ---------------------------------------------------------------------------


def test_voice_memos_are_transcribed_and_only_my_own_feed_voice(unauthenticated_client, db, two, chroma, remote_on):
    mine = _upload(unauthenticated_client, two["ha"], "me.m4a", b"audio", "audio/mp4", author_is_tenant=True)
    forwarded = _upload(unauthenticated_client, two["ha"], "fwd.opus", b"audio", "audio/ogg")
    said = Transcript(text="Mujhe lagta hai tariffs consumers ko hurt karte hain.", language="hindi",
                      duration_seconds=12.5)
    with patch.object(echo_media, "transcribe", return_value=said) as whisper:
        for sid in (mine["id"], forwarded["id"]):
            assert _process(db, sid).state == "processed"
    assert {c.kwargs["tenant_id"] for c in whisper.call_args_list} == {two["a"].id}
    got = _get(unauthenticated_client, two["ha"], mine["id"])
    assert got["extracted_text"] == said.text and got["content_type"] == "voice_memo"
    p = got["processing"]
    assert p["extractor"] == "whisper" and p["language"] == "hindi" and p["duration_seconds"] == 12.5
    assert _vector(chroma, mine["id"])[1]["voice_eligible"] is True
    assert _vector(chroma, forwarded["id"])[1]["voice_eligible"] is False  # context only (D-089)


def test_recordings_stay_on_device_when_remote_media_is_off(unauthenticated_client, db, two, chroma):
    s = _upload(unauthenticated_client, two["ha"], "memo.mp3", b"audio", "audio/mpeg")
    with patch("app.services.youtube_service._whisper_transcribe_with_retry") as whisper:
        result = _process(db, s["id"])
    whisper.assert_not_called()
    assert result.state == "skipped" and "ECHO_REMOTE_MEDIA" in result.reason


def test_a_local_only_tenants_recordings_are_not_transcribed(unauthenticated_client, db, two, chroma, remote_on):
    _make_local_only(db, two["a"].id)
    s = _upload(unauthenticated_client, two["ha"], "memo.mp3", b"audio", "audio/mpeg")
    with patch("app.services.youtube_service._whisper_transcribe_with_retry") as whisper:
        result = _process(db, s["id"])
    whisper.assert_not_called()
    assert result.state == "skipped" and "runs locally" in result.reason


def test_recordings_need_an_openai_key(unauthenticated_client, db, two, chroma, remote_on, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    s = _upload(unauthenticated_client, two["ha"], "memo.mp3", b"audio", "audio/mpeg")
    result = _process(db, s["id"])
    assert result.state == "skipped" and "OpenAI API key" in result.reason


def _whisper_reply(*texts):
    segs = [SimpleNamespace(text=t, start=float(i), end=float(i + 1)) for i, t in enumerate(texts)]
    return SimpleNamespace(language="hindi", duration=float(len(texts)), segments=segs)


@needs_ffmpeg
def test_whisper_gets_ffmpeg_speech_audio_and_the_text_comes_back(unauthenticated_client, db, two, chroma, remote_on, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    s = _upload(unauthenticated_client, two["ha"], "memo.wav", _wav(1.0), "audio/wav")
    seen = {}

    def fake_whisper(client, audio_path, label, tag, size_mb):
        seen["suffix"] = audio_path.rsplit(".", 1)[-1]
        seen["size_mb"] = size_mb
        return _whisper_reply(" नमस्ते ", "hello there")

    with patch("app.services.youtube_service._whisper_transcribe_with_retry", side_effect=fake_whisper):
        assert _process(db, s["id"]).state == "processed"
    assert seen["suffix"] == "mp3" and seen["size_mb"] < 1
    got = _get(unauthenticated_client, two["ha"], s["id"])
    assert got["extracted_text"] == "नमस्ते hello there"
    assert got["processing"]["language"] == "hindi" and got["processing"]["duration_seconds"] == 2.0


@needs_ffmpeg
def test_a_video_clip_without_sound_fails_with_a_reason(unauthenticated_client, db, two, chroma, remote_on, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    silent = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
                    "-pix_fmt", "yuv420p", str(silent)], check=True, capture_output=True, timeout=60)
    s = _upload(unauthenticated_client, two["ha"], "clip.mp4", silent.read_bytes(), "video/mp4")
    with patch("app.services.youtube_service._whisper_transcribe_with_retry") as whisper:
        result = _process(db, s["id"])
    whisper.assert_not_called()
    assert result.state == "failed" and "no audio track" in result.reason


@needs_ffmpeg
def test_a_recording_too_long_for_whisper_fails_with_a_reason(unauthenticated_client, db, two, chroma, remote_on, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("app.services.youtube_service.WHISPER_MAX_FILE_BYTES", 16)
    s = _upload(unauthenticated_client, two["ha"], "memo.wav", _wav(1.0), "audio/wav")
    with patch("app.services.youtube_service._whisper_transcribe_with_retry") as whisper:
        result = _process(db, s["id"])
    whisper.assert_not_called()
    assert result.state == "failed" and "too long" in result.reason


def test_without_ffmpeg_whisper_formats_go_as_they_are(tmp_path, monkeypatch):
    monkeypatch.setattr(echo_media.shutil, "which", lambda _name: None)
    m4a = tmp_path / "a.m4a"
    m4a.write_bytes(b"x")
    assert echo_media._speech_audio(m4a, tmp_path) == m4a
    opus = tmp_path / "b.opus"
    opus.write_bytes(b"x")
    assert echo_media._speech_audio(opus, tmp_path).suffix == ".ogg"
    amr = tmp_path / "c.amr"
    amr.write_bytes(b"x")
    with pytest.raises(MediaError, match="ffmpeg"):
        echo_media._speech_audio(amr, tmp_path)


# ---------------------------------------------------------------------------
# PDFs, long text, everything else
# ---------------------------------------------------------------------------


def test_a_pdf_gives_its_text_layer(unauthenticated_client, db, two, chroma):
    data = _pdf(["Chapter one: who pays for tariffs.", "", "Chapter two: retaliation."])
    s = _upload(unauthenticated_client, two["ha"], "essay.pdf", data, "application/pdf")
    assert _process(db, s["id"]).state == "processed"
    got = _get(unauthenticated_client, two["ha"], s["id"])
    assert "who pays for tariffs" in got["extracted_text"] and "retaliation" in got["extracted_text"]
    p = got["processing"]
    assert p["extractor"] == "pdf_text" and p["page_count"] == 3 and p["pages_with_text"] == 2
    assert "who pays for tariffs" in _vector(chroma, s["id"])[0]


def test_a_pdf_without_a_text_layer_fails_with_a_reason(unauthenticated_client, db, two, chroma):
    s = _upload(unauthenticated_client, two["ha"], "scan.pdf", _pdf(["", ""]), "application/pdf")
    result = _process(db, s["id"])
    assert result.state == "failed" and "scan" in result.reason


def test_long_text_is_capped_and_says_so(unauthenticated_client, db, two, chroma, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARE_TEXT_MAX_CHARS", 100)
    s = _upload(unauthenticated_client, two["ha"], "long.txt", ("word " * 100).encode(), "text/plain")
    _process(db, s["id"])
    got = _get(unauthenticated_client, two["ha"], s["id"])
    assert len(got["extracted_text"]) == 100 and got["processing"]["truncated"] is True
    assert "first 100 of 500" in got["processing"]["note"]


def test_an_unknown_file_is_skipped_and_kept(unauthenticated_client, db, two, chroma):
    s = _upload(unauthenticated_client, two["ha"], "export.zip", b"PK\x03\x04", "application/zip")
    result = _process(db, s["id"])
    assert result.state == "skipped" and "kept in your archive" in result.reason
    got = _get(unauthenticated_client, two["ha"], s["id"])
    assert got["processing_state"] == "skipped" and got["file"]["filename"] == "export.zip"


def test_processing_json_never_holds_the_extracted_text(unauthenticated_client, db, two, chroma, remote_on):
    """The text lives in one place (extracted_text), so the export and the
    deletes have one column to cover, not two."""
    s = _upload(unauthenticated_client, two["ha"], "a.png", _png(), "image/png")
    with patch.object(echo_media, "ocr_local", return_value=CONFIDENT):
        _process(db, s["id"])
    assert CONFIDENT.text not in json.dumps(json.loads(db.get(Share, s["id"]).processing_json))
