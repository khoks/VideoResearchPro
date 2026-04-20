from unittest.mock import patch

from app.models.job import Job


def _make_completed_job(db, report_path="/fake/path/report.html"):
    job = Job(
        job_type="topic",
        topic="report auth test",
        status="completed",
        num_videos=1,
        report_path=report_path,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_report_accepts_query_token(unauthenticated_client, db, auth_token):
    job = _make_completed_job(db)
    with patch("app.routers.qa.report_service.get_report_html", return_value="<html>ok</html>"):
        response = unauthenticated_client.get(
            f"/api/v1/jobs/{job.id}/report?token={auth_token}"
        )
    assert response.status_code == 200
    assert response.text == "<html>ok</html>"


def test_report_still_accepts_header_token(client, db):
    job = _make_completed_job(db)
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
