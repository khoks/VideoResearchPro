"""T-5.6.13: audio is transcribed on the tenant's own key, at the Celery callers.

Echo recordings have always used a tenant's BYOK key; the YouTube fallback and
podcast audio always used the install's ``OPENAI_API_KEY``. The task bodies run
here with only the network replaced, as in ``test_usage_whisper_and_crash``, so
what is pinned is which key the OpenAI client is built with, on each path a
job takes, and that the seconds are still recorded however the key was chosen.

A subscription job is the path a change at the Whisper call alone would miss:
``_run_extraction_and_rag`` meters its run but opened no ``byok_context``, so
there was no tenant in the context to read a key for.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import auth_service, byok_service, llm_service, run_notes, usage_service, youtube_service
from app.tasks import job_tasks
from app.utils.log_redaction import provider_error_text
from tests.test_tasks.test_usage_metering_tasks import _channel_responses
from tests.test_tasks.test_usage_whisper_and_crash import (  # noqa: F401
    WHISPER,
    _approved_job,
    _run_resume,
    _run_sync,
    _sync_job,
    no_captions,
)
from tests.usage_helpers import usage_rows, whisper_api, youtube_network  # noqa: F401

USER_KEY = "fake-placeholder-not-a-key-whisper"
INSTALL_KEY = "fake-placeholder-install-key"


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setattr(settings, "BYOK_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", INSTALL_KEY)
    byok_service._get_fernet.cache_clear()
    yield
    byok_service._get_fernet.cache_clear()


@pytest.fixture
def openai_keys(monkeypatch, whisper_api):  # noqa: F811
    """The key each OpenAI client was built with."""
    keys: list[str | None] = []

    def build(*args, **kwargs):
        keys.append(kwargs.get("api_key"))
        return whisper_api.client

    monkeypatch.setattr("openai.OpenAI", build)
    return keys


_ACCOUNTS = iter(range(10_000))


def _account(db, tier: str = "studio", key: str | None = None):
    user = auth_service.create_user(db, email=f"{tier}{next(_ACCOUNTS)}@example.com", password="pw" * 6)
    user.tier = tier
    db.commit()
    if key:
        byok_service.set_credential(db, user_id=user.id, provider="openai", secret=key)
    return user


def _podcast_job(db, owner, monkeypatch) -> Document:
    from app.sources.podcast import connector

    feed_url = "https://example.com/feed.xml"
    entry = {"id": "ep-1", "title": "Tariffs", "enclosures": [{"href": "https://example.com/ep.mp3"}]}

    def writes(url, path):
        with open(path, "wb") as f:
            f.write(b"mp3 bytes")
        return 9

    monkeypatch.setattr(connector.podcast_client, "get_client", lambda: SimpleNamespace(
        fetch_feed=lambda url: {"feed": {}, "entries": [entry] if url == feed_url else []},
        fetch_audio_to_file=writes,
    ))
    doc = Document(source_type="podcast_episode", source_id="podcast:ep-1", title="Tariffs",
                   url="https://example.com/ep", channel_id=feed_url)
    job = Job(job_type="topic", topic="tariffs", num_videos=1, status="awaiting_approval", tenant_id=owner.id)
    db.add_all([doc, job])
    db.flush()
    db.add(JobVideo(job_id=job.id, document_id=doc.document_id, approved=True))
    db.commit()
    doc.job = job
    return doc


# ---------------------------------------------------------------- the tenant's key


def test_a_jobs_youtube_fallback_runs_on_the_owners_key_and_is_recorded(no_captions, db, whisper_api, openai_keys):  # noqa: F811
    owner = _account(db, key=USER_KEY)
    job = _approved_job(db, owner, ["vByok000001"])

    _run_resume(job)

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    assert openai_keys == [USER_KEY]
    assert usage_rows(db, owner.id) == {WHISPER: 60}


def test_a_subscription_sync_runs_on_the_subscribers_key_and_is_recorded(
    no_captions, db, youtube_network, whisper_api, openai_keys  # noqa: F811
):
    """``_run_extraction_and_rag`` opened no ``byok_context`` of its own, so
    this is the path a fix at the Whisper call alone leaves on the install."""
    owner = _account(db, key=USER_KEY)
    job = _sync_job(db, owner)
    youtube_network.responses = _channel_responses(["vByok000002", "vByok000003"])

    _run_sync(job)

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    assert openai_keys == [USER_KEY, USER_KEY]
    assert usage_rows(db, owner.id)[WHISPER] == 120


def test_a_long_recording_sends_every_chunk_on_the_owners_key(
    no_captions, db, whisper_api, openai_keys, monkeypatch, tmp_path  # noqa: F811
):
    """One client for the whole recording, so every chunk is on the same key."""
    from tests.test_tasks.test_usage_whisper_and_crash import _split_into

    owner = _account(db, key=USER_KEY)
    _split_into(monkeypatch, tmp_path, 3)
    whisper_api.seconds = 300.0

    with llm_service.byok_context(owner.id, db):
        assert youtube_service._transcribe_with_whisper("vByokLong01") is not None

    assert openai_keys == [USER_KEY]
    assert whisper_api.sent == 3
    assert usage_rows(db, owner.id) == {WHISPER: 900}


def test_a_jobs_podcast_audio_runs_on_the_owners_key_and_is_recorded(no_captions, db, whisper_api, openai_keys, monkeypatch):  # noqa: F811
    owner = _account(db, key=USER_KEY)
    doc = _podcast_job(db, owner, monkeypatch)

    _run_resume(doc.job)

    db.expire_all()
    assert db.get(Document, doc.document_id).transcript_source == "podcast_whisper"
    assert openai_keys == [USER_KEY]
    assert usage_rows(db, owner.id) == {WHISPER: 60}


def test_an_install_with_no_key_of_its_own_still_reads_a_tenants_podcast(no_captions, db, whisper_api, openai_keys, monkeypatch):  # noqa: F811
    """The gate in front of the download asked the install alone, so a user
    who brought a key lost the episode anyway."""
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    owner = _account(db, key=USER_KEY)
    doc = _podcast_job(db, owner, monkeypatch)

    _run_resume(doc.job)

    db.expire_all()
    assert db.get(Document, doc.document_id).transcript_source == "podcast_whisper"
    assert openai_keys == [USER_KEY]


# ---------------------------------------------------------------- nothing else moves


def test_without_a_key_of_their_own_a_user_stays_on_the_install_key(no_captions, db, whisper_api, openai_keys):  # noqa: F811
    owner = _account(db)
    job = _approved_job(db, owner, ["vPlain00001"])

    _run_resume(job)

    assert openai_keys == [INSTALL_KEY]
    assert usage_rows(db, owner.id) == {WHISPER: 60}


def test_without_a_key_a_podcast_stays_on_the_install_key(no_captions, db, whisper_api, openai_keys, monkeypatch):  # noqa: F811
    owner = _account(db)
    doc = _podcast_job(db, owner, monkeypatch)

    _run_resume(doc.job)

    assert openai_keys == [INSTALL_KEY]
    assert usage_rows(db, owner.id) == {WHISPER: 60}


def test_a_tier_without_keys_stays_on_the_install_key_on_audio_too(no_captions, db, whisper_api, openai_keys):  # noqa: F811
    """A stored key from before a downgrade is not honoured here either."""
    owner = _account(db, tier="free", key=USER_KEY)
    job = _approved_job(db, owner, ["vDowngrade1"])

    _run_resume(job)

    assert openai_keys == [INSTALL_KEY]


def test_with_no_key_anywhere_a_podcast_is_left_unread_without_a_request(no_captions, db, whisper_api, openai_keys, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    owner = _account(db)
    doc = _podcast_job(db, owner, monkeypatch)

    _run_resume(doc.job)

    assert openai_keys == [] and whisper_api.sent == 0


def test_outside_a_jobs_context_audio_stays_on_the_install_key(no_captions, db, whisper_api, openai_keys):  # noqa: F811
    """An operator script opens no scope, so it has no tenant to read for."""
    assert youtube_service._transcribe_with_whisper("vScript0001") is not None
    assert openai_keys == [INSTALL_KEY]


def test_mutation_a_scope_with_no_byok_context_leaves_the_audio_on_the_install(no_captions, db, whisper_api, openai_keys):  # noqa: F811
    """A metering scope names the tenant to charge, not the key to use. This
    is why ``_run_extraction_and_rag`` needed the context around ``fetch_text``."""
    owner = _account(db, key=USER_KEY)

    with usage_service.metered(db, owner.id):
        assert youtube_service._transcribe_with_whisper("vScopeOnly1") is not None

    assert openai_keys == [INSTALL_KEY]
    assert usage_rows(db, owner.id) == {WHISPER: 60}


def test_a_refused_tenant_key_does_not_fall_back_to_the_install(no_captions, db, whisper_api, openai_keys):  # noqa: F811
    """As a model call on a user's key: their audio is never quietly moved to
    the install's bill because their own key failed."""
    from unittest.mock import MagicMock

    from openai import AuthenticationError

    owner = _account(db, key=USER_KEY)

    def refuse(api):
        raise AuthenticationError("refused", response=MagicMock(status_code=401), body=None)

    whisper_api.before_send = refuse

    with llm_service.byok_context(owner.id, db):
        assert youtube_service._transcribe_with_whisper("vRefused001") is None

    assert openai_keys == [USER_KEY]


def _refused(key_text: str):
    from unittest.mock import MagicMock

    from openai import AuthenticationError

    def refuse(api):
        raise AuthenticationError(f"Incorrect API key provided: {key_text}", response=MagicMock(status_code=401), body=None)

    return refuse


def test_a_refused_tenant_key_leaves_nothing_of_it_in_the_log(no_captions, db, whisper_api, openai_keys, monkeypatch):  # noqa: F811
    """OpenAI quotes a refused key in part. That was the operator's own key
    in the operator's own log; now it can be a tenant's. On the logger itself:
    ``caplog`` depends on global logging state."""
    from unittest.mock import patch

    owner = _account(db, key=USER_KEY)
    whisper_api.before_send = _refused(USER_KEY)

    with patch.object(youtube_service, "logger") as log, llm_service.byok_context(owner.id, db):
        assert youtube_service._transcribe_with_whisper("vRefused002") is None

    assert "AuthenticationError" in repr(log.mock_calls), "the failure is still logged"
    assert USER_KEY not in repr(log.mock_calls)


def test_a_refused_tenant_key_stays_out_of_a_split_recordings_log(
    no_captions, db, whisper_api, openai_keys, monkeypatch, tmp_path  # noqa: F811
):
    from unittest.mock import patch

    from tests.test_tasks.test_usage_whisper_and_crash import _split_into

    owner = _account(db, key=USER_KEY)
    _split_into(monkeypatch, tmp_path, 2)
    whisper_api.before_send = _refused(USER_KEY)

    with patch.object(youtube_service, "logger") as log, llm_service.byok_context(owner.id, db):
        assert youtube_service._transcribe_with_whisper("vRefused003") is None

    assert USER_KEY not in repr(log.mock_calls)


def test_a_refused_tenant_key_stays_out_of_a_podcasts_log(no_captions, db, whisper_api, openai_keys, monkeypatch):  # noqa: F811
    from unittest.mock import patch

    from app.sources.podcast import connector

    owner = _account(db, key=USER_KEY)
    doc = _podcast_job(db, owner, monkeypatch)
    whisper_api.before_send = _refused(USER_KEY)

    with patch.object(connector, "logger") as log, patch.object(youtube_service, "logger") as shared_log:
        with llm_service.byok_context(owner.id, db):
            assert connector._whisper_transcribe_audio("https://example.com/ep.mp3", doc.source_id, "j") is None

    assert USER_KEY not in repr(log.mock_calls) + repr(shared_log.mock_calls)


def test_any_other_whisper_failure_keeps_its_words_in_the_log():
    """A 400 "file too large" is what an operator needs to read."""
    assert provider_error_text(ValueError("file too large")) == "file too large"


# ---------------------------------------------------------------- a template's warning


def _podcast_template_params():
    from app.schemas.job_template import TemplateParameters

    return TemplateParameters(job_type="topic", source_types=["podcast_episode"])


def test_a_template_warns_about_transcription_only_when_no_key_can_do_it(db, monkeypatch):
    """"This install has not set up Whisper" was true of a user with no key,
    and is untrue of one whose key Whisper now runs on."""
    from app.services import job_template_service

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 50)
    # The next warning down is about ffmpeg, which a test machine may not have.
    monkeypatch.setattr("app.services.job_source_types.shutil.which", lambda name: f"/usr/bin/{name}")
    params = _podcast_template_params()

    with_key = _account(db, key=USER_KEY)
    without_key = _account(db)
    downgraded = _account(db, tier="free", key=USER_KEY)

    assert not any("Whisper" in p for p in job_template_service.problems_for(db, params, with_key))
    assert any("Whisper" in p for p in job_template_service.problems_for(db, params, without_key))
    assert any("Whisper" in p for p in job_template_service.problems_for(db, params, downgraded))


def test_echo_recordings_keep_the_rule_they_shared_with_the_rest(db):
    """The same function now answers all three paths."""
    from app.services import echo_media

    assert echo_media._openai_key(_account(db, key=USER_KEY).id, db) == USER_KEY
    assert echo_media._openai_key(_account(db).id, db) == INSTALL_KEY


# ---------------------------------------------------------------- the job's budget
#
# WHISPER_MAX_PER_JOB on a sync, which has no approval step. Before this the
# loop passed no budget, so a channel's whole history could go to Whisper, on
# the subscriber's own account once T-5.6.13 moved the fallback there, and
# ``0`` did not turn it off. These run the real task; only the network is fake.

UPLOADS = ["vBudget0001", "vBudget0002", "vBudget0003"]


def _read_and_unread(db) -> tuple[int, int]:
    db.expire_all()
    statuses = [d.transcript_status for d in db.query(Document)]
    return statuses.count("fetched"), statuses.count("unavailable")


def _notes(db, job) -> list[dict]:
    db.expire_all()
    return run_notes.read(db.get(Job, job.id))


@pytest.mark.parametrize("own_key", [USER_KEY, None], ids=["own key", "install key"])
def test_a_sync_stops_at_the_recording_budget(
    no_captions, db, youtube_network, whisper_api, openai_keys, monkeypatch, own_key  # noqa: F811
):
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    owner = _account(db, key=own_key)
    job = _sync_job(db, owner)
    youtube_network.responses = _channel_responses(UPLOADS)

    _run_sync(job)

    assert whisper_api.sent == 1
    assert openai_keys == [own_key or INSTALL_KEY]
    assert _read_and_unread(db) == (1, 2)
    assert db.get(Job, job.id).status == "completed"


@pytest.mark.parametrize("budget", [0, -1])
def test_a_budget_of_zero_turns_whisper_off_on_a_sync(
    no_captions, db, youtube_network, whisper_api, openai_keys, monkeypatch, budget  # noqa: F811
):
    """What CLAUDE.md and the template have always said the setting does."""
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", budget)
    job = _sync_job(db, _account(db, key=USER_KEY))
    youtube_network.responses = _channel_responses(UPLOADS)

    _run_sync(job)

    assert whisper_api.sent == 0
    assert openai_keys == []
    assert _read_and_unread(db) == (0, 3)
    assert db.get(Job, job.id).status == "failed"
    assert [n["text"] for n in _notes(db, job)] == [
        "Whisper is off on this install (WHISPER_MAX_PER_JOB), so 3 sources could not be read. "
        "A later sync tries them again."
    ]


def test_a_video_with_captions_spends_none_of_the_budget_on_a_sync(
    no_captions, db, youtube_network, whisper_api, openai_keys, monkeypatch  # noqa: F811
):
    """The first upload the loop reaches has captions, whichever that is: the
    query has no order, so naming a video here would pass or fail by luck."""
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    asked: list[str] = []

    def captions_for_the_first(video_id, *args, **kwargs):
        asked.append(video_id)
        if video_id != asked[0]:
            return None
        return [{"text": "words from a caption track", "start": 0.0, "duration": 5.0}], "en", None

    monkeypatch.setattr(youtube_service, "_fetch_transcript_once", captions_for_the_first)
    job = _sync_job(db, _account(db, key=USER_KEY))
    youtube_network.responses = _channel_responses(UPLOADS)

    _run_sync(job)

    assert whisper_api.sent == 1
    assert _read_and_unread(db) == (2, 1)


def test_the_next_sync_reads_what_the_budget_left(
    no_captions, db, youtube_network, whisper_api, openai_keys, monkeypatch  # noqa: F811
):
    """A capped upload is unread, not lost. This is what makes the cap safe to
    apply to a channel with many uncaptioned videos: each sync links the whole
    channel again, and takes the next budget's worth."""
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    owner = _account(db)
    youtube_network.responses = _channel_responses(UPLOADS)

    for run, expected in enumerate([(1, 2), (2, 1), (3, 0)], start=1):
        job = _sync_job(db, owner)
        _run_sync(job)
        assert whisper_api.sent == run
        assert _read_and_unread(db) == expected

    assert _notes(db, job) == [], "the last sync lost nothing to the budget"


def test_a_sync_says_what_the_budget_cost_it(
    no_captions, db, youtube_network, whisper_api, openai_keys, monkeypatch  # noqa: F811
):
    """"Completed successfully" is all a fire-and-forget run leaves behind, and
    the progress line that names the budget moves on."""
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 1)
    job = _sync_job(db, _account(db))
    youtube_network.responses = _channel_responses(UPLOADS)

    _run_sync(job)

    assert _notes(db, job) == [{
        "kind": run_notes.WHISPER_BUDGET_SPENT,
        "text": (
            "Whisper stopped at this run's limit of 1 recording (WHISPER_MAX_PER_JOB), so "
            "2 sources could not be read. A later sync tries them again."
        ),
    }]
    published = [c.args[3] for c in job_tasks.progress_service.publish_progress.call_args_list]
    assert any("Whisper budget exhausted" in m for m in published)


def test_a_sync_within_the_budget_has_nothing_to_say(
    no_captions, db, youtube_network, whisper_api, openai_keys, monkeypatch  # noqa: F811
):
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", len(UPLOADS))
    job = _sync_job(db, _account(db))
    youtube_network.responses = _channel_responses(UPLOADS)

    _run_sync(job)

    assert whisper_api.sent == len(UPLOADS)
    assert _read_and_unread(db) == (3, 0)
    assert _notes(db, job) == []
