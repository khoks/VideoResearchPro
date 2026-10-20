from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.dependencies import get_db
from app.main import app
from app.services import auth_service, rate_limit_service

# E-5.5: disable the rate limiter globally for the test suite. Individual
# rate-limit tests opt back in by toggling settings.RATE_LIMIT_ENABLED via
# monkeypatch and resetting the in-memory bucket between tests.
settings.RATE_LIMIT_ENABLED = False

# T-1.16.2.5 part B: rendering non-English chunks into English is an LLM call
# inside `chroma_service.insert_chunks`. Off for the suite so no test that
# inserts Hindi chunks can reach a provider; the feature's own tests opt back
# in with a stubbed model.
settings.CODE_MIX_ENGLISH_RENDERING_ENABLED = False
# S-8.5.2: the notes index embeds on every note write and is queried by
# every Q&A call. Off for the suite so no router test loads the embedder
# or touches a persistent collection; the notes-retrieval tests opt back
# in against an in-memory Chroma.
settings.NOTES_INDEX_ENABLED = False
# S-3.7.2: Echo share processing is queued to Celery in production. Off for
# the suite (shares stay pending); the processing tests call the processor
# directly with every external call patched.
settings.ECHO_SHARE_PROCESSING = "off"
# S-3.7.2 part 2: no shared image or recording may reach a remote provider
# from the suite. Tests of the vision fallback and Whisper turn this back on
# with the remote call patched.
settings.ECHO_REMOTE_MEDIA = False
# S-1.14.19: map batches run concurrently in production. Stub LLMs that hand
# out responses in call order need one batch at a time; the concurrent path
# has its own tests that set this back up.
settings.REPORT_MAP_CONCURRENCY = 1

# Tests must never touch the developer's database, the network or a wallet.
# The app lifespan runs schema init against ``settings.DATABASE_URL``, a Chroma
# backfill, and the real LLM smoke probes. Point schema init at a scratch file
# (read at lifespan time, so mutating settings here is enough; the engine
# ``app.database`` built at import is unused by tests because ``get_db`` is
# overridden below) and stub the other two for the whole session. Found
# 2026-10-19: the dev DB had been migrated by an unmerged branch and every
# router test errored at startup, and each ``TestClient`` had been spending on
# six real provider probes.
settings.DATABASE_URL = "sqlite:///" + (Path(__file__).resolve().parent / ".pytest_schema.db").as_posix()
# S-6.1.5: a book's PDF needs an optional converter (WeasyPrint or Chromium).
# Off for the suite, so a book test behaves the same on every machine and
# does not pay for a browser; the PDF tests turn it back on and skip when
# this machine has no engine.
settings.AUTHOR_PDF_ENGINE = "off"


@pytest.fixture(scope="session", autouse=True)
def _isolate_outputs_dir(tmp_path_factory):
    # S-6.1.5: every generated book now writes an EPUB under OUTPUTS_DIR.
    # Without this the suite would fill ./data/outputs of the checkout it
    # runs in; tests that inspect the files still set their own root.
    previous = settings.OUTPUTS_DIR
    settings.OUTPUTS_DIR = str(tmp_path_factory.mktemp("outputs"))
    yield
    settings.OUTPUTS_DIR = previous


@pytest.fixture(scope="session", autouse=True)
def _isolate_app_lifespan():
    # Replace only ``app.main``'s binding of the chroma module, wrapping the
    # real one, so the lifespan's backfill is a no-op while tests that call
    # ``chroma_service.backfill_qa_library`` directly still get the real thing.
    from app.services import chroma_service as _real_chroma

    _chroma_for_lifespan = MagicMock(wraps=_real_chroma)
    _chroma_for_lifespan.backfill_qa_library = MagicMock(return_value=None)
    _chroma_for_lifespan.backfill_chunk_document_ids = MagicMock(return_value=0)
    with (
        patch("app.main.run_startup_probes", new=AsyncMock(return_value=None)),
        patch("app.main.chroma_service", new=_chroma_for_lifespan),
    ):
        yield

SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        # E-5.5: clear rate-limit bucket state between tests so a test
        # that opted into rate-limiting can't bleed into subsequent tests.
        rate_limit_service.reset()


@pytest.fixture
def test_user(db):
    """Create a persistent test user and return it."""
    user = auth_service.create_user(db, email="test@example.com", password="testpass123")
    return user


@pytest.fixture
def auth_token(test_user):
    """Issue a JWT for the test user."""
    token, _ = auth_service.create_access_token(test_user.id)
    return token


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def client(db, auth_headers):
    """Test client that automatically sends the test user's auth token on every request."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    # Mock Celery task dispatch so tests don't need Redis. T-5.6.5 routes
    # via apply_async (per-tier queue) instead of delay; mock both so any
    # call shape returns an AsyncResult with a real string id.
    with (
        patch("app.routers.jobs.execute_topic_job") as mock_topic,
        patch("app.routers.jobs.execute_channel_job") as mock_channel,
        patch("app.routers.jobs.execute_subscription_job") as mock_subscription,
        patch("app.routers.jobs.resume_job_after_approval") as mock_resume,
        # S-6.7.1: Author Studio generation is a Celery task too.
        patch("app.routers.author.generate_output") as mock_generate_output,
        # S-1.18.2: on-demand frame capture.
        patch("app.routers.frames.extract_frames") as mock_extract_frames,
    ):
        mock_topic.delay.return_value = MagicMock(id="mock-topic-task-id")
        mock_topic.apply_async.return_value = MagicMock(id="mock-topic-task-id")
        mock_channel.delay.return_value = MagicMock(id="mock-channel-task-id")
        mock_channel.apply_async.return_value = MagicMock(id="mock-channel-task-id")
        mock_subscription.delay.return_value = MagicMock(id="mock-subscription-task-id")
        mock_subscription.apply_async.return_value = MagicMock(
            id="mock-subscription-task-id"
        )
        mock_resume.delay.return_value = MagicMock(id="mock-resume-task-id")
        mock_resume.apply_async.return_value = MagicMock(id="mock-resume-task-id")
        mock_generate_output.apply_async.return_value = MagicMock(id="mock-generate-output-task-id")
        mock_extract_frames.apply_async.return_value = MagicMock(id="mock-extract-frames-task-id")
        with TestClient(app, headers=auth_headers) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(db):
    """Test client without auth headers — for testing auth enforcement."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with (
        patch("app.routers.jobs.execute_topic_job") as mock_topic,
        patch("app.routers.jobs.execute_channel_job") as mock_channel,
        patch("app.routers.jobs.execute_subscription_job") as mock_subscription,
        patch("app.routers.jobs.resume_job_after_approval") as mock_resume,
        # S-6.7.1: Author Studio generation is a Celery task too.
        patch("app.routers.author.generate_output") as mock_generate_output,
        # S-1.18.2: on-demand frame capture.
        patch("app.routers.frames.extract_frames") as mock_extract_frames,
    ):
        mock_topic.delay.return_value = MagicMock(id="mock-topic-task-id")
        mock_topic.apply_async.return_value = MagicMock(id="mock-topic-task-id")
        mock_channel.delay.return_value = MagicMock(id="mock-channel-task-id")
        mock_channel.apply_async.return_value = MagicMock(id="mock-channel-task-id")
        mock_subscription.delay.return_value = MagicMock(id="mock-subscription-task-id")
        mock_subscription.apply_async.return_value = MagicMock(
            id="mock-subscription-task-id"
        )
        mock_resume.delay.return_value = MagicMock(id="mock-resume-task-id")
        mock_resume.apply_async.return_value = MagicMock(id="mock-resume-task-id")
        mock_generate_output.apply_async.return_value = MagicMock(id="mock-generate-output-task-id")
        mock_extract_frames.apply_async.return_value = MagicMock(id="mock-extract-frames-task-id")
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture
def seeded_global_library(db, test_user):
    """Pre-populate the global `videos` and `channels` tables with synthetic data,
    OWNED by ``test_user``.

    Shared by any test that needs an existing library without re-creating it.

    S-5.7.1: `documents` is a shared cache with no tenant of its own; ownership
    is derived from the jobs that selected a document. Library listings are now
    scoped that way, so seeded documents must be linked to a job owned by the
    authenticated test user or they are (correctly) invisible.
    """
    from app.models.channel import Channel
    from app.models.document import Document

    now = datetime.now(timezone.utc)

    channels = []
    for i in range(2):
        channels.append(
            Channel(
                channel_id=f"UC{'A' * 20}{i:02d}",
                name=f"Channel {i}",
            )
        )
    db.add_all(channels)
    db.commit()

    videos = []
    for i in range(5):
        vid = f"vid{i:03d}abcXYZ"
        videos.append(
            Document(
                video_id=vid,
                title=f"Seeded Video {i}",
                channel_id=f"UC{'A' * 20}{i % 2:02d}",
                url=f"https://www.youtube.com/watch?v={vid}",
                duration_seconds=300 + i * 60,
                published_at=now,
                thumbnail_url=f"https://img/{vid}.jpg",
                transcript_status="pending",
                created_at=now,
            )
        )
    db.add_all(videos)
    db.commit()
    # Ownership: one job for the authenticated test user, selecting all seeded
    # documents. Without this the library listing correctly returns nothing.
    from app.models.job import Job
    from app.models.job_video import JobVideo

    job = Job(
        id="seeded-library-job",
        tenant_id=test_user.id,
        job_type="topic",
        topic="Seeded library job",
        status="completed",
        created_at=now,
    )
    db.add(job)
    db.commit()
    db.add_all(
        [JobVideo(job_id=job.id, video_id=v.video_id, approved=True) for v in videos]
    )
    db.commit()

    for v in videos:
        db.refresh(v)
    for c in channels:
        db.refresh(c)

    return {"videos": videos, "channels": channels, "job": job}
