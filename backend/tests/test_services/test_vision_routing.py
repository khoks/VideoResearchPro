"""Vision use cases must not be able to probe green off a text-only check.

`visual_describe_frame` is the app's first multimodal call site. Everything
in the registry before it was freely swappable across providers and models;
this one is not. Two failure modes are specific to it and both are silent:

* pointing it at a text-only model, which either 400s at run time or (worse)
  describes the image from surrounding text and sounds right;
* sharing a startup probe with a text use case on the same (provider, model),
  which reports healthy without ever having sent an image.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.llm_routing import (
    USE_CASE_REGISTRY,
    UseCaseConfig,
    VISION_USE_CASES,
    is_vision_use_case,
    warn_if_not_vision_capable,
)
from app.services.llm_smoke import _collect_probe_targets, _dedupe_key


def test_vision_use_cases_are_registered():
    for uc in VISION_USE_CASES:
        assert uc in USE_CASE_REGISTRY


def test_is_vision_use_case():
    assert is_vision_use_case("visual_describe_frame")
    # The selector reads a transcript; it never sees an image.
    assert not is_vision_use_case("visual_select_moments")
    assert not is_vision_use_case("report_compose")


def test_a_text_only_model_behind_a_vision_use_case_warns():
    assert warn_if_not_vision_capable(
        "visual_describe_frame", UseCaseConfig("openai", "gpt-5.6-luna", "low")
    ) is True
    assert warn_if_not_vision_capable(
        "visual_describe_frame", UseCaseConfig("openai", "some-text-only-model", "low")
    ) is False


def test_local_provider_is_exempt_from_the_vision_warning():
    """We cannot know what an operator loaded into LM Studio, and refusing to
    run would be worse than letting them find out."""
    assert warn_if_not_vision_capable(
        "visual_describe_frame", UseCaseConfig("local", "whatever", "low")
    ) is True


def test_the_warning_never_blocks():
    """Same fail-soft rule as the rest of llm_routing: the capability list
    will always lag new model releases, so it advises and does not gate."""
    assert warn_if_not_vision_capable(
        "visual_describe_frame", UseCaseConfig("openai", "unknown-2027", "low")
    ) is False  # returns a verdict, raises nothing


def test_vision_and_text_configs_do_not_share_a_probe():
    """THE regression this guards: identical (provider, model), different
    question. A shared probe answers the text question and reports the vision
    one healthy."""
    cfg = UseCaseConfig("openai", "gpt-5.5", "low")
    assert _dedupe_key(cfg, True) != _dedupe_key(cfg, False)


def test_probe_targets_mark_the_vision_use_case():
    targets = _collect_probe_targets()
    vision_keys = [k for k in targets if k[2] is True]
    assert vision_keys, "no vision probe target collected"
    covered = {uc for k in vision_keys for uc in targets[k][1]}
    assert "visual_describe_frame" in covered
    # And it must not have been folded in with the text use cases.
    for key, (_cfg, use_cases) in targets.items():
        if key[2] is False:
            assert "visual_describe_frame" not in use_cases


def test_vision_probe_actually_sends_an_image():
    from app.services.llm_service import probe_config

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="ok")
    cfg = UseCaseConfig("openai", "gpt-5.5", "off")

    with patch("app.services.llm_service._build_from_config", return_value=fake_llm):
        result = probe_config(cfg, vision=True)

    assert result.ok
    content = fake_llm.invoke.call_args[0][0][0].content
    assert isinstance(content, list)
    assert any(p["type"] == "image_url" for p in content)


def test_probe_image_is_a_valid_png():
    """The first version of this constant was plausible-looking and malformed;
    OpenAI returned `image_parse_error`, which would have made every vision
    probe report the model unreachable — a startup banner blaming the
    provider for our own broken bytes."""
    import base64
    import struct
    import zlib

    from app.services.llm_service import _PROBE_IMAGE_B64

    data = base64.b64decode(_PROBE_IMAGE_B64)
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG signature"

    # Walk the chunks and verify each CRC — the check a decoder performs.
    pos, tags = 8, []
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF, f"bad CRC in {tag!r}"
        tags.append(tag)
        pos += 12 + length
    assert tags[0] == b"IHDR" and tags[-1] == b"IEND"
    assert b"IDAT" in tags

    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (16, 16)


def test_text_probe_stays_a_plain_string():
    from app.services.llm_service import probe_config

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="ok")

    with patch("app.services.llm_service._build_from_config", return_value=fake_llm):
        probe_config(UseCaseConfig("openai", "gpt-5.5", "off"), vision=False)

    assert isinstance(fake_llm.invoke.call_args[0][0][0].content, str)


def test_probe_handles_a_reasoning_block_list_response():
    """`probe_config` documents that it never raises, but read `.content`
    directly and a reasoning model's block list makes `.strip()` an
    AttributeError — thrown from inside the startup lifespan."""
    from app.services.llm_service import probe_config

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(
        content=[
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "ok"},
        ]
    )
    with patch("app.services.llm_service._build_from_config", return_value=fake_llm):
        result = probe_config(UseCaseConfig("anthropic", "claude-opus-5", "medium"))
    assert result.ok


def test_probe_fails_when_only_thinking_comes_back():
    from app.services.llm_service import probe_config

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(
        content=[{"type": "thinking", "thinking": "..."}]
    )
    with patch("app.services.llm_service._build_from_config", return_value=fake_llm):
        result = probe_config(UseCaseConfig("anthropic", "claude-opus-5", "medium"))
    assert not result.ok
    assert "empty" in (result.error or "")


def test_visual_analysis_is_its_own_health_feature():
    """A vision outage must grey out the visual toggle without making the
    whole topic-job type look unavailable."""
    from app.services.llm_smoke import FEATURE_TO_USE_CASES

    assert set(FEATURE_TO_USE_CASES["visual_analysis"]) == {
        "visual_select_moments",
        "visual_describe_frame",
    }
    assert "visual_describe_frame" not in FEATURE_TO_USE_CASES["topic_job"]
