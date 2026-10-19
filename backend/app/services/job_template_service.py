"""Job templates — the single accessor (S-8.6.1 / E-8.6).

Built-ins (``tenant_id`` NULL) are visible to every reader and writable by
none; a reader's own templates are visible and writable only to them; a
deleted template is gone from every listing and lookup but its versions stay
so job provenance keeps resolving. Foreign ids resolve to ``None`` and the
routers return 404.

Validation re-runs ``JobCreate`` on the parameters (with a placeholder topic
for topic templates), so a template can never hold a recipe that would fail
at submission, and ``problems_for`` reports what would stop *this* reader
from using it today (a tier cap below its ``num_videos``).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.job_template import JobTemplate, JobTemplateVersion
from app.models.user import User
from app.schemas.job import JobCreate
from app.schemas.job_template import TemplateParameters
from app.services.tier_service import get_user_tier, quota_limit

logger = logging.getLogger(__name__)

MAX_VERSIONS = 20
TOPIC_PLACEHOLDER = "{{topic}}"


class TemplateNameTaken(Exception):
    """Another live template of this reader has the name (case-insensitive)."""


class BuiltinReadOnly(Exception):
    """Built-in templates cannot be changed or deleted."""


class InvalidParameters(Exception):
    """The parameters would not make a valid job."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

def validate_parameters(params: TemplateParameters) -> None:
    """Raise ``InvalidParameters`` unless the parameters plus a topic make a
    valid ``JobCreate`` — the same validation a submission goes through."""
    payload = params.model_dump()
    if params.job_type == "topic":
        payload["topic"] = "placeholder topic"
    try:
        JobCreate(**payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise InvalidParameters(str(first.get("msg", "invalid parameters")).replace("Value error, ", ""))


def problems_for(params: TemplateParameters, user: User) -> list[str]:
    """What would stop ``user`` from running this template today."""
    problems: list[str] = []
    if params.job_type == "topic":
        cap = quota_limit(user, "num_videos_cap")
        if cap != -1 and params.num_videos > cap:
            problems.append(
                f"Asks for {params.num_videos} videos; the {get_user_tier(user).value} "
                f"plan allows {cap}. Lower it after loading."
            )
    return problems


def parameters_from_job(job: Job) -> TemplateParameters:
    """The frozen half of an existing run, as a template would store it."""

    def _list(raw: str | None) -> list[str] | None:
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, list) and value else None

    is_topic = job.job_type == "topic"
    return TemplateParameters(
        job_type=job.job_type,
        search_instructions=job.search_instructions if is_topic else None,
        num_videos=job.num_videos or 10,
        min_duration_minutes=job.min_duration_minutes,
        max_duration_minutes=job.max_duration_minutes,
        channel_type_filters=_list(job.channel_type_filters) if is_topic else None,
        preferred_channels=_list(job.preferred_channels) if is_topic else None,
        output_length=job.output_length,
        visual_analysis=bool(job.visual_analysis),
        channel_list=None if is_topic else _list(job.channel_list),
        videos_per_channel=job.videos_per_channel if job.job_type == "channel" else None,
    )


def fill_topic(instructions: str | None, topic: str | None) -> str | None:
    """Replace ``{{topic}}`` in search instructions with the run's topic."""
    if not instructions or not topic or TOPIC_PLACEHOLDER not in instructions:
        return instructions
    return instructions.replace(TOPIC_PLACEHOLDER, topic)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _visible(db: Session, tenant_id: str):
    return db.query(JobTemplate).filter(
        JobTemplate.deleted_at.is_(None),
        or_(JobTemplate.tenant_id == tenant_id, JobTemplate.tenant_id.is_(None)),
    )


def list_templates(db: Session, tenant_id: str) -> list[JobTemplate]:
    """The reader's own templates A→Z, then the built-ins A→Z."""
    rows = _visible(db, tenant_id).all()
    return sorted(rows, key=lambda t: (t.is_builtin, t.name.lower()))


def get_template(db: Session, template_id: str, tenant_id: str) -> JobTemplate | None:
    return _visible(db, tenant_id).filter(JobTemplate.id == template_id).first()


def get_version(db: Session, template: JobTemplate, version: int | None = None) -> JobTemplateVersion | None:
    return db.get(JobTemplateVersion, (template.id, version or template.latest_version))


def latest_parameters(db: Session, template: JobTemplate) -> TemplateParameters:
    row = get_version(db, template)
    return TemplateParameters(**json.loads(row.parameters_json))


def versions(db: Session, template: JobTemplate) -> list[JobTemplateVersion]:
    return (
        db.query(JobTemplateVersion)
        .filter(JobTemplateVersion.template_id == template.id)
        .order_by(JobTemplateVersion.version.desc())
        .all()
    )


def _name_taken(db: Session, tenant_id: str, name: str, *, exclude_id: str | None = None) -> bool:
    q = db.query(JobTemplate.id).filter(
        JobTemplate.tenant_id == tenant_id,
        JobTemplate.deleted_at.is_(None),
        func.lower(JobTemplate.name) == name.lower(),
    )
    if exclude_id is not None:
        q = q.filter(JobTemplate.id != exclude_id)
    return db.query(q.exists()).scalar() is True


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def _dump(params: TemplateParameters) -> str:
    return json.dumps(params.model_dump(), sort_keys=True)


def create_template(
    db: Session,
    tenant_id: str,
    name: str,
    params: TemplateParameters,
    description: str | None = None,
) -> JobTemplate:
    validate_parameters(params)
    if _name_taken(db, tenant_id, name):
        raise TemplateNameTaken(name)
    template = JobTemplate(
        tenant_id=tenant_id,
        name=name,
        description=description,
        job_type=params.job_type,
        latest_version=1,
    )
    db.add(template)
    db.flush()
    db.add(JobTemplateVersion(template_id=template.id, version=1, parameters_json=_dump(params)))
    db.commit()
    db.refresh(template)
    return template


_UNSET = object()


def update_template(
    db: Session,
    template: JobTemplate,
    *,
    name: str | object = _UNSET,
    description: str | None | object = _UNSET,
    params: TemplateParameters | object = _UNSET,
) -> JobTemplate:
    """Rename / redescribe in place; new parameters become a new version
    (unchanged parameters do not). Keeps the newest ``MAX_VERSIONS``."""
    if template.is_builtin:
        raise BuiltinReadOnly(template.id)
    if params is not _UNSET:
        assert isinstance(params, TemplateParameters)
        validate_parameters(params)
        if params.job_type != template.job_type:
            raise InvalidParameters("A template cannot change its research type.")
    if name is not _UNSET:
        assert isinstance(name, str)
        if _name_taken(db, template.tenant_id, name, exclude_id=template.id):
            raise TemplateNameTaken(name)
        template.name = name
    if description is not _UNSET:
        template.description = description  # type: ignore[assignment]
    if params is not _UNSET:
        current = get_version(db, template)
        dumped = _dump(params)  # type: ignore[arg-type]
        if current is None or current.parameters_json != dumped:
            template.latest_version += 1
            db.add(
                JobTemplateVersion(
                    template_id=template.id,
                    version=template.latest_version,
                    parameters_json=dumped,
                )
            )
            db.flush()
            _prune(db, template)
    template.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(template)
    return template


def _prune(db: Session, template: JobTemplate) -> None:
    keep_from = template.latest_version - MAX_VERSIONS + 1
    if keep_from <= 1:
        return
    db.query(JobTemplateVersion).filter(
        JobTemplateVersion.template_id == template.id,
        JobTemplateVersion.version < keep_from,
    ).delete(synchronize_session=False)


def delete_template(db: Session, template: JobTemplate) -> None:
    """Soft delete: hidden everywhere, versions kept for job provenance."""
    if template.is_builtin:
        raise BuiltinReadOnly(template.id)
    template.deleted_at = datetime.now(timezone.utc)
    db.commit()


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def template_to_dict(db: Session, template: JobTemplate, user: User) -> dict:
    params = latest_parameters(db, template)
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "job_type": template.job_type,
        "builtin": template.is_builtin,
        "builtin_key": template.builtin_key,
        "version": template.latest_version,
        "parameters": params,
        "problems": problems_for(params, user),
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }
