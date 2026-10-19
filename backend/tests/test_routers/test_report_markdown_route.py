"""S-6.1.2 — ``GET /api/v1/jobs/{id}/report.md``: the Markdown source over
HTTP. Header-bearer auth only, tenant-scoped like every job route, and it
writes the cache beside the HTML the first time it is read."""
from __future__ import annotations

from pathlib import Path

from app.models.job import Job
from app.services import auth_service, report_service

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "reports" / "topic_three_videos.html"


def _job_with_report(db, tenant_id: str, tmp_path: Path, job_id: str = "md-job") -> Job:
    report = tmp_path / f"report_{job_id}.html"
    report.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    job = Job(id=job_id, tenant_id=tenant_id, job_type="topic", status="completed",
              topic="pratidhvani smoke test", report_path=str(report))
    db.add(job)
    db.commit()
    return job


def test_report_md_returns_markdown_and_caches_it(client, db, test_user, tmp_path):
    job = _job_with_report(db, test_user.id, tmp_path)
    r = client.get(f"/api/v1/jobs/{job.id}/report.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert 'filename="report-md-job.md"' in r.headers["content-disposition"]
    body = r.text
    assert body.startswith("# Research Report: pratidhvani smoke test")
    assert "## Executive Summary" in body
    assert "| Videos Analyzed | Transcripts Fetched | Total Words | Total Minutes |" in body
    assert "&t=" in body and "<div" not in body
    assert Path(report_service.markdown_path_for(job.report_path)).read_text(encoding="utf-8") == body


def test_report_md_is_tenant_scoped(client, db, tmp_path):
    other = auth_service.create_user(db, email="other-md@x.com", password="pw" * 6)
    job = _job_with_report(db, other.id, tmp_path, job_id="their-job")
    r = client.get(f"/api/v1/jobs/{job.id}/report.md")
    assert r.status_code == 404
    assert "pratidhvani" not in r.text


def test_report_md_404_without_report_or_file(client, db, test_user, tmp_path):
    db.add(Job(id="no-report", tenant_id=test_user.id, job_type="topic", status="completed", topic="x"))
    db.add(Job(id="gone-file", tenant_id=test_user.id, job_type="topic", status="completed", topic="y",
               report_path=str(tmp_path / "missing.html")))
    db.commit()
    assert client.get("/api/v1/jobs/no-report/report.md").json()["detail"] == "Report not generated yet"
    assert client.get("/api/v1/jobs/gone-file/report.md").json()["detail"] == "Report file not found"
    assert client.get("/api/v1/jobs/nope/report.md").status_code == 404


def test_report_md_requires_a_header_token_never_a_query_token(unauthenticated_client, db, test_user, tmp_path):
    job = _job_with_report(db, test_user.id, tmp_path)
    assert unauthenticated_client.get(f"/api/v1/jobs/{job.id}/report.md").status_code == 401
    token, _ = auth_service.create_access_token(test_user.id)
    r = unauthenticated_client.get(f"/api/v1/jobs/{job.id}/report.md", params={"token": token})
    assert r.status_code == 401, "a ?token= must not authenticate this route"
    r = unauthenticated_client.get(
        f"/api/v1/jobs/{job.id}/report.md", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200


def test_html_report_route_still_serves_html(client, db, test_user, tmp_path):
    """The sibling `/report` (HTML, routers/qa.py) must not be shadowed."""
    job = _job_with_report(db, test_user.id, tmp_path)
    r = client.get(f"/api/v1/jobs/{job.id}/report")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
