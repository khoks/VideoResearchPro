"""Report body route for the native reader (S-8.8.1).

Lives in its own router rather than ``routers/qa.py`` so the reader can land
without touching the Q&A router, which the retrieval work serialises on. The
legacy HTML route (``GET /jobs/{id}/report``, query-token fallback for the
iframe) stays in ``routers/qa.py`` until T-8.8.1.5 retires it.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.schemas.report import ReportBodyResponse
from app.services import job_service, report_service

router = APIRouter(
    prefix="/jobs/{job_id}/report",
    tags=["reports"],
    # Header-bearer auth ONLY. The whole point of this route is that the
    # reader never needs a ``?token=`` in a URL (a log-leak surface).
    dependencies=[Depends(get_current_user)],
)


@router.get("/body", response_model=ReportBodyResponse)
def get_report_body(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    job = job_service.get_job(db, job_id, tenant_id=current_user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.report_path:
        raise HTTPException(status_code=404, detail="Report not generated yet")

    document = report_service.get_report_html(job.report_path)
    if not document:
        raise HTTPException(status_code=404, detail="Report file not found")

    parts = report_service.extract_report_body(document)
    return ReportBodyResponse(
        job_id=job.id,
        job_type=job.job_type,
        title=parts["title"],
        html=parts["html"],
        statistics=parts["statistics"],
        generated_at=parts["generated_at"],
    )
