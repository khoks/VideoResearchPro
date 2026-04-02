from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.dependencies import get_db
from app.main import app

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
def client(db):
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
        patch("app.routers.jobs.resume_job_after_approval") as mock_resume,
    ):
        mock_topic.delay.return_value = None
        mock_channel.delay.return_value = None
        mock_resume.delay.return_value = None
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()
