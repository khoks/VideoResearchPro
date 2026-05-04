def test_create_topic_job(client):
    response = client.post("/api/v1/jobs", json={
        "job_type": "topic",
        "topic": "quantum computing",
        "num_videos": 5,
    })
    assert response.status_code == 201
    data = response.json()
    assert data["job_type"] == "topic"
    assert data["topic"] == "quantum computing"
    assert data["status"] == "pending"
    assert data["num_videos"] == 5
    assert data["progress_pct"] == 0


def test_create_channel_job(client):
    response = client.post("/api/v1/jobs", json={
        "job_type": "channel",
        "channel_list": ["@3blue1brown", "@Veritasium"],
        "videos_per_channel": 5,
    })
    assert response.status_code == 201
    data = response.json()
    assert data["job_type"] == "channel"
    assert data["channel_list"] == ["@3blue1brown", "@Veritasium"]


def test_create_topic_job_missing_topic(client):
    response = client.post("/api/v1/jobs", json={
        "job_type": "topic",
    })
    assert response.status_code == 422


def test_create_channel_job_missing_channels(client):
    response = client.post("/api/v1/jobs", json={
        "job_type": "channel",
    })
    assert response.status_code == 422


def test_list_jobs(client):
    # Create two jobs
    client.post("/api/v1/jobs", json={"job_type": "topic", "topic": "AI"})
    client.post("/api/v1/jobs", json={"job_type": "topic", "topic": "ML"})

    response = client.get("/api/v1/jobs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_get_job(client):
    create_resp = client.post("/api/v1/jobs", json={"job_type": "topic", "topic": "physics"})
    job_id = create_resp.json()["id"]

    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["topic"] == "physics"


def test_get_job_not_found(client):
    response = client.get("/api/v1/jobs/nonexistent")
    assert response.status_code == 404


def test_cancel_job(client):
    create_resp = client.post("/api/v1/jobs", json={"job_type": "topic", "topic": "test"})
    job_id = create_resp.json()["id"]

    response = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_completed_job_fails(client, db, test_user):
    from app.models.job import Job
    # Per E-5.1 phase 2b, the cancel endpoint filters by tenant_id;
    # tag the job with the test user's id so it's reachable.
    job = Job(
        job_type="topic",
        topic="done",
        status="completed",
        num_videos=5,
        tenant_id=test_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    response = client.post(f"/api/v1/jobs/{job.id}/cancel")
    assert response.status_code == 400


def test_delete_job(client):
    create_resp = client.post("/api/v1/jobs", json={"job_type": "topic", "topic": "delete me"})
    job_id = create_resp.json()["id"]

    response = client.delete(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 204

    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 404


def test_get_job_videos_empty(client):
    create_resp = client.post("/api/v1/jobs", json={"job_type": "topic", "topic": "test"})
    job_id = create_resp.json()["id"]

    response = client.get(f"/api/v1/jobs/{job_id}/videos")
    assert response.status_code == 200
    assert response.json() == []
