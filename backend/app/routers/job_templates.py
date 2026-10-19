"""Job templates REST (S-8.6.1 / E-8.6).

Not tier-gated (M6 plan: templates cost the operator nothing). Built-ins
are listed for everyone and are read-only (403 on any write); another
reader's template is a 404. Saving a run as a template lives on the jobs
router (`POST /jobs/{id}/save-as-template`); starting a run from one is
`POST /jobs?template_id=&template_version=`.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.job_template import (
    JobTemplateCreate,
    JobTemplateResponse,
    JobTemplateUpdate,
    JobTemplateVersionResponse,
    TemplateParameters,
)
from app.services import job_template_service as svc
from app.services.job_template_service import (
    BuiltinReadOnly,
    InvalidParameters,
    TemplateNameTaken,
)

router = APIRouter(
    prefix="/job-templates",
    tags=["job-templates"],
    dependencies=[Depends(get_current_user)],
)


def template_or_404(db: Session, template_id: str, tenant_id: str):
    template = svc.get_template(db, template_id, tenant_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


def name_conflict(name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"You already have a template named '{name}'.",
    )


def invalid(exc: InvalidParameters) -> HTTPException:
    return HTTPException(status_code=422, detail=f"This template would not make a valid run: {exc.message}")


BUILTIN_READ_ONLY = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Starter templates are read-only. Load one and save your own copy.",
)


@router.get("", response_model=list[JobTemplateResponse])
def list_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return [svc.template_to_dict(db, t, current_user) for t in svc.list_templates(db, current_user.id)]


@router.post("", response_model=JobTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(
    body: JobTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        template = svc.create_template(db, current_user.id, body.name, body.parameters, body.description)
    except TemplateNameTaken:
        raise name_conflict(body.name)
    except InvalidParameters as exc:
        raise invalid(exc)
    return svc.template_to_dict(db, template, current_user)


@router.get("/{template_id}", response_model=JobTemplateResponse)
def get_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return svc.template_to_dict(db, template_or_404(db, template_id, current_user.id), current_user)


@router.put("/{template_id}", response_model=JobTemplateResponse)
def update_template(
    template_id: str,
    body: JobTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = template_or_404(db, template_id, current_user.id)
    sent = body.model_fields_set
    kwargs: dict = {}
    if "name" in sent and body.name is not None:
        kwargs["name"] = body.name
    if "description" in sent:
        kwargs["description"] = body.description
    if "parameters" in sent and body.parameters is not None:
        kwargs["params"] = body.parameters
    try:
        template = svc.update_template(db, template, **kwargs)
    except BuiltinReadOnly:
        raise BUILTIN_READ_ONLY
    except TemplateNameTaken:
        raise name_conflict(body.name or "")
    except InvalidParameters as exc:
        raise invalid(exc)
    return svc.template_to_dict(db, template, current_user)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = template_or_404(db, template_id, current_user.id)
    try:
        svc.delete_template(db, template)
    except BuiltinReadOnly:
        raise BUILTIN_READ_ONLY


@router.get("/{template_id}/versions", response_model=list[JobTemplateVersionResponse])
def list_versions(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = template_or_404(db, template_id, current_user.id)
    return [
        {
            "version": v.version,
            "parameters": TemplateParameters(**json.loads(v.parameters_json)),
            "created_at": v.created_at,
        }
        for v in svc.versions(db, template)
    ]
