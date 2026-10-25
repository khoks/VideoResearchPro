"""S-8.8.1: ``GET /jobs/{id}/report/body`` — the reader's JSON route.

Header auth only: a token in a URL leaks through logs and Referer headers.
The legacy HTML route took ``?token=`` for its iframe until T-8.8.1.5; this
one never did.
"""

from unittest.mock import patch

from app.models.job import Job
from app.utils.html_builder import build_report_html

_STATS = {
    "video_count": 2,
    "transcript_count": 2,
    "total_words": 1500,
    "total_minutes": 30,
    "channel_breakdown": [{"channel_name": "Ch", "video_count": 2, "word_count": 1500, "minutes": 30}],
}
_BODY = '<section class="report"><h2>Summary</h2><p>Hello.</p></section>'


def _document(title="Research Report: body route"):
    return build_report_html(title=title, job_type="topic", statistics=_STATS, report_body=_BODY)


def _make_job(db, tenant_id, report_path="/fake/report.html", job_type="topic"):
    job = Job(
        job_type=job_type,
        topic="body route",
        status="completed",
        num_videos=2,
        report_path=report_path,
        tenant_id=tenant_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_body_route_returns_parts_under_header_auth(client, db, test_user):
    job = _make_job(db, test_user.id)
    with patch("app.routers.reports.report_service.get_report_html", return_value=_document()):
        response = client.get(f"/api/v1/jobs/{job.id}/report/body")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["job_id"] == job.id
    assert data["job_type"] == "topic"
    assert data["title"] == "Research Report: body route"
    assert data["html"] == _BODY
    assert data["statistics"]["video_count"] == 2
    assert data["statistics"]["channel_breakdown"][0]["channel_name"] == "Ch"
    assert data["generated_at"]


def test_body_route_rejects_query_token(unauthenticated_client, db, auth_token, test_user):
    """The iframe-era fallback must not apply here."""
    job = _make_job(db, test_user.id)
    with patch("app.routers.reports.report_service.get_report_html", return_value=_document()):
        response = unauthenticated_client.get(
            f"/api/v1/jobs/{job.id}/report/body?token={auth_token}"
        )
    assert response.status_code == 401


def test_body_route_rejects_anonymous(unauthenticated_client, db, test_user):
    job = _make_job(db, test_user.id)
    response = unauthenticated_client.get(f"/api/v1/jobs/{job.id}/report/body")
    assert response.status_code == 401


def test_body_route_404_when_no_report(client, db, test_user):
    job = _make_job(db, test_user.id, report_path=None)
    response = client.get(f"/api/v1/jobs/{job.id}/report/body")
    assert response.status_code == 404
    assert response.json()["detail"] == "Report not generated yet"


def test_body_route_404_when_file_missing(client, db, test_user):
    job = _make_job(db, test_user.id, report_path="/definitely/not/here.html")
    response = client.get(f"/api/v1/jobs/{job.id}/report/body")
    assert response.status_code == 404
    assert response.json()["detail"] == "Report file not found"


def test_body_route_hides_other_tenants_jobs(client, db):
    job = _make_job(db, tenant_id="someone-else")
    with patch("app.routers.reports.report_service.get_report_html", return_value=_document()):
        response = client.get(f"/api/v1/jobs/{job.id}/report/body")
    assert response.status_code == 404
