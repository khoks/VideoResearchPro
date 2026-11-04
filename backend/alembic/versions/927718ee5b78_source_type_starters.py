"""two source-type starters — podcast digest, mixed-source debate (S-8.6.4)

Revision ID: 927718ee5b78
Revises: b84e405ab989
Create Date: 2026-11-04

Data-only. The two starters the M6 plan proposed that `f1a2b3c4d5e6` could
not ship, because `JobCreate` had no `source_types` until S-1.5.13 (D-082). As
D-082 requires, this revision carries its own frozen copy of `_upsert` and of
its definitions, and app code never feeds it.

`STARTERS` here holds only the two new built-ins. The five from `f1a2b3c4d5e6`
have not changed, so copying them would only risk versioning them by accident,
and the downgrade walks this list, so it removes these two and nothing else.

Why these sources. A migration cannot vary by install, so a starter may only
name sources that need no search credential; a credential-gated one (Reddit,
web articles, X) would show as a problem on a stock install. The reader can add
those after loading. Finding podcasts takes no credential, but reading one with
no published transcript takes Whisper after approval, so `problems_for` says so
on an install without it. Two ungated sources are left out on evidence from a live
check on 2026-11-04: Bluesky's public `searchPosts` answered 403, which the
connector turns into an empty list, and Mastodon searches one hashtag made by
joining the words of the topic, which found nothing for a phrase. A run's
budget is split in advance (D-114), so a source that returns nothing wastes
its share.

`search_instructions` steers the search agent and connectors ignore it, so the
podcast digest leaves it empty and the debate's reaches its YouTube half only.
Neither turns on visual analysis (D-109) or sets a publish window: only
YouTube results are ranked (S-8.6.3).

Downgrade removes these two built-ins and their versions. Runs that started
from one keep their `template_id` (no foreign key), as with any deleted
template.
"""
import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "927718ee5b78"
down_revision = "b84e405ab989"
branch_labels = None
depends_on = None

_BASE = {
    "search_instructions": None,
    "num_videos": 10,
    "min_duration_minutes": None,
    "max_duration_minutes": None,
    "channel_type_filters": None,
    "preferred_channels": None,
    "output_length": None,
    "visual_analysis": False,
    "source_types": None,
    "published_after_days": None,
    "channel_list": None,
    "videos_per_channel": None,
}

STARTERS = [
    {
        "builtin_key": "podcast-digest",
        "name": "Podcast digest",
        "description": (
            "Recent episodes from the shows that cover a subject, in a brief report. "
            "Episodes with no published transcript are transcribed after you approve them."
        ),
        "job_type": "topic",
        "parameters": {
            **_BASE,
            "job_type": "topic",
            "num_videos": 8,
            "output_length": "brief",
            "source_types": ["podcast_episode"],
        },
    },
    {
        "builtin_key": "mixed-source-debate",
        "name": "Mixed-source debate",
        "description": (
            "Where people disagree about a subject: talks, podcasts and Hacker News "
            "threads, read side by side. Works best with a short subject, not a full question. "
            "Episodes with no published transcript are transcribed after you approve them."
        ),
        "job_type": "topic",
        "parameters": {
            **_BASE,
            "job_type": "topic",
            "num_videos": 18,
            "source_types": ["video", "hn_story", "podcast_episode"],
            "search_instructions": (
                "The live disagreements about {{topic}}: debates, critiques and replies from "
                "people who hold different positions. Prefer argument over news clips and "
                "reaction videos."
            ),
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
