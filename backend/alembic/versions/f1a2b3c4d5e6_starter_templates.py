"""starter job templates — five read-only built-ins (S-8.6.2 / E-8.6)

Revision ID: f1a2b3c4d5e6
Revises: f0a1b2c3d4e5
Create Date: 2026-10-19

Data-only. Inserts the built-in templates (`tenant_id` NULL) every reader
sees under "Starters". Each is keyed by a stable `builtin_key`; the upsert is
idempotent and versioned: a key that exists with identical parameters is left
alone, one whose parameters differ gets the next version. A later migration
that revises a starter's text copies `STARTERS` and `_upsert` and changes the
entry; it never edits this file. The definitions live here, not in app code,
so this revision keeps meaning what it meant when it ran.

Why these five. The M6 plan proposed topic scan, channel deep-dive, podcast
digest, mixed-source debate and subscription follow, and left the choice to
the user. Podcast digest and mixed-source debate need `source_types`, which
`JobCreate` does not accept today (nothing writes `jobs.source_types_json`;
see S-8.6.1's finding), so they are replaced by "Deep dive" and "Quick brief"
until that field is wired. None turns on visual analysis: its opt-in is
deferred by D-071 / D-075, and a starter must not become that opt-in.

Downgrade removes these built-ins and their versions. Runs that started from
one keep their `template_id` (no foreign key), as with any deleted template.
"""
import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None

# Every JobCreate field but `topic`; channel lists are left empty on the
# channel starters, which the template layer reads as "you add the channels".
_BASE = {
    "search_instructions": None,
    "num_videos": 10,
    "min_duration_minutes": None,
    "max_duration_minutes": None,
    "channel_type_filters": None,
    "preferred_channels": None,
    "output_length": None,
    "visual_analysis": False,
    "channel_list": None,
    "videos_per_channel": None,
}

STARTERS = [
    {
        "builtin_key": "topic-scan",
        "name": "Topic scan",
        "description": "A first map of a subject: the main positions and who holds them, from about twenty sources.",
        "job_type": "topic",
        "parameters": {
            **_BASE,
            "job_type": "topic",
            "num_videos": 20,
            "search_instructions": (
                "Survey the main positions on {{topic}}. Prefer explainers, lectures and "
                "long-form discussion over news clips and reaction videos."
            ),
        },
    },
    {
        "builtin_key": "deep-dive",
        "name": "Deep dive",
        "description": "Sixty long-form sources and a deep report, for a subject you mean to know well.",
        "job_type": "topic",
        "parameters": {
            **_BASE,
            "job_type": "topic",
            "num_videos": 60,
            "min_duration_minutes": 15,
            "output_length": "deep",
            "search_instructions": (
                "In-depth, long-form material on {{topic}}: lectures, interviews, debates and "
                "talks by people who work on it. Skip shorts, compilations and reaction videos."
            ),
        },
    },
    {
        "builtin_key": "quick-brief",
        "name": "Quick brief",
        "description": "Eight short, clear sources and a brief report, when you need the gist today.",
        "job_type": "topic",
        "parameters": {
            **_BASE,
            "job_type": "topic",
            "num_videos": 8,
            "max_duration_minutes": 30,
            "output_length": "brief",
            "search_instructions": "The clearest, most recent explainers on {{topic}}.",
        },
    },
    {
        "builtin_key": "channel-deep-dive",
        "name": "Channel deep-dive",
        "description": "What a few channels have said: their recent uploads, read together. Add the channels each time.",
        "job_type": "channel",
        "parameters": {
            **_BASE,
            "job_type": "channel",
            "num_videos": 10,
            "videos_per_channel": 25,
        },
    },
    {
        "builtin_key": "subscription-follow",
        "name": "Subscription follow",
        "description": "Shelve every upload from channels you follow, so you can ask across all of it. Add the channels each time.",
        "job_type": "subscription",
        "parameters": {
            **_BASE,
            "job_type": "subscription",
        },
    },
]


def _dump(params: dict) -> str:
    return json.dumps(params, sort_keys=True)


def _upsert(conn, starter: dict) -> None:
    """Insert a built-in, or add a version when its parameters changed."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = conn.execute(
        sa.text("SELECT id, latest_version FROM job_templates WHERE builtin_key = :k"),
        {"k": starter["builtin_key"]},
    ).first()
    dumped = _dump(starter["parameters"])
    if row is None:
        template_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO job_templates (id, tenant_id, builtin_key, name, description, job_type, "
                "latest_version, created_at, updated_at) VALUES "
                "(:id, NULL, :k, :name, :d, :jt, 1, :now, :now)"
            ),
            {
                "id": template_id,
                "k": starter["builtin_key"],
                "name": starter["name"],
                "d": starter["description"],
                "jt": starter["job_type"],
                "now": now,
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO job_template_versions (template_id, version, parameters_json, created_at) "
                "VALUES (:id, 1, :p, :now)"
            ),
            {"id": template_id, "p": dumped, "now": now},
        )
        return
    template_id, latest = row
    current = conn.execute(
        sa.text(
            "SELECT parameters_json FROM job_template_versions WHERE template_id = :id AND version = :v"
        ),
        {"id": template_id, "v": latest},
    ).scalar()
    conn.execute(
        sa.text(
            "UPDATE job_templates SET name = :name, description = :d, deleted_at = NULL WHERE id = :id"
        ),
        {"id": template_id, "name": starter["name"], "d": starter["description"]},
    )
    if current is not None and json.loads(current) == starter["parameters"]:
        return
    conn.execute(
        sa.text(
            "INSERT INTO job_template_versions (template_id, version, parameters_json, created_at) "
            "VALUES (:id, :v, :p, :now)"
        ),
        {"id": template_id, "v": latest + 1, "p": dumped, "now": now},
    )
    conn.execute(
        sa.text("UPDATE job_templates SET latest_version = :v, updated_at = :now WHERE id = :id"),
        {"id": template_id, "v": latest + 1, "now": now},
    )


def upgrade() -> None:
    conn = op.get_bind()
    for starter in STARTERS:
        _upsert(conn, starter)


def downgrade() -> None:
    conn = op.get_bind()
    keys = [s["builtin_key"] for s in STARTERS]
    for key in keys:
        row = conn.execute(
            sa.text("SELECT id FROM job_templates WHERE builtin_key = :k"), {"k": key}
        ).first()
        if row is None:
            continue
        conn.execute(sa.text("DELETE FROM job_template_versions WHERE template_id = :id"), {"id": row[0]})
        conn.execute(sa.text("DELETE FROM job_templates WHERE id = :id"), {"id": row[0]})
