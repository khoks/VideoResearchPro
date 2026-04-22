"""Tests for the Whisper retry helper and YouTube IP-block short-circuit.

Both behaviours were added in response to a live 100-video job that
burned ~5 minutes per Whisper failure (default SDK timeout too long) and
retried futilely against YouTube's rate-limiter (14s wasted per IP-blocked
video). These tests pin the new policy:

1. ``_whisper_transcribe_with_retry`` retries on APIConnectionError /
   APITimeoutError / InternalServerError, re-raises on BadRequestError /
   AuthenticationError / PermissionDeniedError without retry.
2. ``_is_ip_block_signal`` matches the known exception names and message
   fragments emitted by youtube-transcript-api + urllib3 when YouTube
   closes connections.
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.services import youtube_service


# ---------- _is_ip_block_signal classification -------------------------------


def test_ip_block_signal_detects_named_exceptions():
    class IpBlocked(Exception):
        pass

    class RequestBlocked(Exception):
        pass

    class RemoteDisconnected(Exception):
        pass

    assert youtube_service._is_ip_block_signal(IpBlocked("blocked"))
    assert youtube_service._is_ip_block_signal(RequestBlocked("nope"))
    assert youtube_service._is_ip_block_signal(RemoteDisconnected("closed"))


def test_ip_block_signal_detects_message_fragments():
    assert youtube_service._is_ip_block_signal(
        Exception("YouTube is blocking requests from your IP")
    )
    assert youtube_service._is_ip_block_signal(
        Exception(("Connection aborted.", "RemoteDisconnected(...)"))
    )


def test_ip_block_signal_rejects_normal_errors():
    assert not youtube_service._is_ip_block_signal(Exception("no transcript"))
    assert not youtube_service._is_ip_block_signal(ValueError("bad input"))
    assert not youtube_service._is_ip_block_signal(
        Exception("TranscriptsDisabled: this video has captions disabled")
    )


# ---------- _whisper_transcribe_with_retry behaviour -------------------------


def _make_audio_file() -> str:
    """Create a tiny throwaway file so ``open(audio_path, 'rb')`` succeeds."""
    fd, path = tempfile.mkstemp(suffix=".m4a")
    os.write(fd, b"fake audio bytes")
    os.close(fd)
    return path


@pytest.fixture
def audio_path():
    path = _make_audio_file()
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


def test_whisper_retry_succeeds_on_first_attempt(audio_path):
    """Happy path: no retry needed."""
    client = MagicMock()
    client.with_options.return_value = client
    fake_response = MagicMock(language="en", duration=1.0, segments=[])
    client.audio.transcriptions.create.return_value = fake_response

    result = youtube_service._whisper_transcribe_with_retry(
        client, audio_path, "vid123", "[job:t]", audio_size_mb=5.0
    )

    assert result is fake_response
    assert client.audio.transcriptions.create.call_count == 1
    # Explicit timeout was applied.
    client.with_options.assert_called_once()
    assert client.with_options.call_args.kwargs["timeout"] == youtube_service._WHISPER_REQUEST_TIMEOUT


def test_whisper_retry_recovers_after_transient_failure(audio_path, monkeypatch):
    """APIConnectionError on attempt 1 → succeeds on attempt 2."""
    from openai import APIConnectionError

    # Skip the real sleep between retries to keep the test fast.
    monkeypatch.setattr(youtube_service.time, "sleep", lambda _: None)

    client = MagicMock()
    client.with_options.return_value = client
    fake_response = MagicMock(language="en", duration=1.0, segments=[])
    client.audio.transcriptions.create.side_effect = [
        APIConnectionError(request=MagicMock()),
        fake_response,
    ]

    result = youtube_service._whisper_transcribe_with_retry(
        client, audio_path, "vid123", "[job:t]", audio_size_mb=5.0
    )

    assert result is fake_response
    assert client.audio.transcriptions.create.call_count == 2


def test_whisper_retry_exhausts_on_repeated_connection_errors(audio_path, monkeypatch):
    """3 consecutive APIConnectionErrors → raises the last one."""
    from openai import APIConnectionError

    monkeypatch.setattr(youtube_service.time, "sleep", lambda _: None)

    client = MagicMock()
    client.with_options.return_value = client
    client.audio.transcriptions.create.side_effect = APIConnectionError(request=MagicMock())

    with pytest.raises(APIConnectionError):
        youtube_service._whisper_transcribe_with_retry(
            client, audio_path, "vid123", "[job:t]", audio_size_mb=5.0
        )

    assert client.audio.transcriptions.create.call_count == youtube_service._WHISPER_MAX_ATTEMPTS


def test_whisper_retry_does_not_retry_bad_request(audio_path, monkeypatch):
    """BadRequestError (400 e.g. file too large) is re-raised immediately."""
    from openai import BadRequestError

    sleep_calls = []
    monkeypatch.setattr(youtube_service.time, "sleep", lambda s: sleep_calls.append(s))

    client = MagicMock()
    client.with_options.return_value = client
    bad = BadRequestError(
        message="Invalid file format",
        response=MagicMock(status_code=400),
        body={"error": {"message": "bad"}},
    )
    client.audio.transcriptions.create.side_effect = bad

    with pytest.raises(BadRequestError):
        youtube_service._whisper_transcribe_with_retry(
            client, audio_path, "vid123", "[job:t]", audio_size_mb=5.0
        )

    # Single call — no retry, no backoff sleep.
    assert client.audio.transcriptions.create.call_count == 1
    assert sleep_calls == []


def test_whisper_retry_does_not_retry_auth_error(audio_path, monkeypatch):
    """AuthenticationError (401) is re-raised immediately — bad keys won't fix."""
    from openai import AuthenticationError

    sleep_calls = []
    monkeypatch.setattr(youtube_service.time, "sleep", lambda s: sleep_calls.append(s))

    client = MagicMock()
    client.with_options.return_value = client
    err = AuthenticationError(
        message="bad key",
        response=MagicMock(status_code=401),
        body={"error": {"message": "bad"}},
    )
    client.audio.transcriptions.create.side_effect = err

    with pytest.raises(AuthenticationError):
        youtube_service._whisper_transcribe_with_retry(
            client, audio_path, "vid123", "[job:t]", audio_size_mb=5.0
        )

    assert client.audio.transcriptions.create.call_count == 1
    assert sleep_calls == []
