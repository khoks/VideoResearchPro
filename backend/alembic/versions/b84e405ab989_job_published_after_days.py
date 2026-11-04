"""jobs.published_after_days — a relative publish window (S-8.6.3 / D-112)

Revision ID: b84e405ab989
Revises: 5f8caf39b5b1
Create Date: 2026-11-04

NULL means no preference, so existing jobs keep exactly today's ranking
prompt. Days, not a date: the search agent turns it into a date when the run
ranks, which is what lets a template mean "the last 30 days" for as long as it
is used. A ranking preference, never a filter (D-059, D-072). The upgrade is
purely additive.

The downgrade also takes `published_after_days` out of every stored template
version. The app writes every parameter on save, so each version saved after
this upgrade carries the key, and the previous revision's `TemplateParameters`
forbids extra keys: left in place, one such row fails `GET /job-templates` for
its reader.
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "b84e405ab989"
down_revision = "5f8caf39b5b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("published_after_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT template_id, version, parameters_json FROM job_template_versions")
    ).fetchall()
    for template_id, version, raw in rows:
        try:
            params = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(params, dict) or "published_after_days" not in params:
            continue
        del params["published_after_days"]
        conn.execute(
            sa.text(
                "UPDATE job_template_versions SET parameters_json = :p "
                "WHERE template_id = :t AND version = :v"
            ),
            {"p": json.dumps(params, sort_keys=True), "t": template_id, "v": version},
        )
    op.drop_column("jobs", "published_after_days")
