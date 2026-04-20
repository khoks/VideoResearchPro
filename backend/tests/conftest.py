from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.dependencies import get_db
from app.main import app
from app.services import auth_service

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

    # Mock Celery task dispatch so tests don't need Redis
    with (
        patch("app.routers.jobs.execute_topic_job") as mock_topic,
        patch("app.routers.jobs.execute_channel_job") as mock_channel,
        patch("app.routers.jobs.execute_subscription_job") as mock_subscription,
        patch("app.routers.jobs.resume_job_after_approval") as mock_resume,
    ):
        # Router code reads `.id` off AsyncResult to track the Celery task.
        mock_topic.delay.return_value = MagicMock(id="mock-topic-task-id")
        mock_channel.delay.return_value = MagicMock(id="mock-channel-task-id")
        mock_subscription.delay.return_value = MagicMock(id="mock-subscription-task-id")
        mock_resume.delay.return_value = MagicMock(id="mock-resume-task-id")
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
    ):
        mock_topic.delay.return_value = MagicMock(id="mock-topic-task-id")
        mock_channel.delay.return_value = MagicMock(id="mock-channel-task-id")
        mock_subscription.delay.return_value = MagicMock(id="mock-subscription-task-id")
        mock_resume.delay.return_value = MagicMock(id="mock-resume-task-id")
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture
def seeded_global_library(db):
    """Pre-populate the global `videos` and `channels` tables with synthetic data.

    Shared by any test that needs an existing library without re-creating it.
    """
    from app.models.channel import Channel
    from app.models.video import Video

    now = datetime.now(timezone.utc)

    channels = []
    for i in range(2):
        channels.append(
            Channel(
                channel_id=f"UC{'A' * 20}{i:02d}",
                name=f"Channel {i}",
                subscribed=False,
            )
        )
    db.add_all(channels)
    db.commit()

    videos = []
    for i in range(5):
        vid = f"vid{i:03d}abcXYZ"
        videos.append(
            Video(
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
    for v in videos:
        db.refresh(v)
    for c in channels:
        db.refresh(c)

    return {"videos": videos, "channels": channels}
