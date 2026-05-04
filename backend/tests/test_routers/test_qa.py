from unittest.mock import patch

from app.models.job import Job


def _make_completed_job(
    db, report_path="/fake/path/report.html", tenant_id: str | None = None
):
    """Build a completed topic Job for the report endpoint tests.

    `tenant_id` (E-5.1 phase 2b) — set to the test user's id so the
    job is reachable via the tenant-scoped report endpoint filter.
    """
    job = Job(
        job_type="topic",
        topic="report auth test",
        status="completed",
        num_videos=1,
        report_path=report_path,
        tenant_id=tenant_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_report_accepts_query_token(unauthenticated_client, db, auth_token, test_user):
    job = _make_completed_job(db, tenant_id=test_user.id)
    with patch("app.routers.qa.report_service.get_report_html", return_value="<html>ok</html>"):
        response = unauthenticated_client.get(
            f"/api/v1/jobs/{job.id}/report?token={auth_token}"
        )
    assert response.status_code == 200
    assert response.text == "<html>ok</html>"


def test_report_still_accepts_header_token(client, db, test_user):
    job = _make_completed_job(db, tenant_id=test_user.id)
    with patch("app.routers.qa.report_service.get_report_html", return_value="<html>ok</html>"):
        response = client.get(f"/api/v1/jobs/{job.id}/report")
    assert response.status_code == 200


def test_report_rejects_when_no_token(unauthenticated_client, db):
    job = _make_completed_job(db)
    response = unauthenticated_client.get(f"/api/v1/jobs/{job.id}/report")
    assert response.status_code == 401


def test_report_rejects_bad_query_token(unauthenticated_client, db):
    job = _make_completed_job(db)
    response = unauthenticated_client.get(
        f"/api/v1/jobs/{job.id}/report?token=not-a-real-jwt"
    )
    assert response.status_code == 401


def test_qa_history_does_not_accept_query_token(unauthenticated_client, db, auth_token):
    # The scoped query-token fallback must not leak to other QA routes —
    # /qa and /qa/clarify still require the Authorization header.
    job = _make_completed_job(db)
    response = unauthenticated_client.get(
        f"/api/v1/jobs/{job.id}/qa?token={auth_token}"
    )
    assert response.status_code == 401
