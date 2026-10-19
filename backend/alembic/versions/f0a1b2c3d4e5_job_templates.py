"""job_templates + job_template_versions + jobs provenance (S-8.6.1 / E-8.6)

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-10-19

Additive. `job_templates` is a template's identity and editable metadata
(`tenant_id` NULL for built-ins, `builtin_key` unique, soft delete through
`deleted_at`); `job_template_versions` holds one immutable parameters row
per saved change. `jobs.template_id` / `jobs.template_version` record which
template version a run started from. No foreign key from `jobs`: templates
are soft-deleted and provenance must keep resolving.
"""
import sqlalchemy as sa
from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("builtin_key", sa.String(60), nullable=True, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("job_type", sa.String(20), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_job_templates_tenant_id", "job_templates", ["tenant_id"])

    op.create_table(
        "job_template_versions",
        sa.Column(
            "template_id",
            sa.String(36),
            sa.ForeignKey("job_templates.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.add_column("jobs", sa.Column("template_id", sa.String(36), nullable=True))
    op.add_column("jobs", sa.Column("template_version", sa.Integer(), nullable=True))
    op.create_index("ix_jobs_template_id", "jobs", ["template_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_template_id", table_name="jobs")
    op.drop_column("jobs", "template_version")
    op.drop_column("jobs", "template_id")
    op.drop_table("job_template_versions")
    op.drop_index("ix_job_templates_tenant_id", table_name="job_templates")
    op.drop_table("job_templates")
