"""shelves + shelf_jobs — named per-tenant collections of jobs (S-8.1.1 / E-8.1)

Revision ID: d8e9f0a1b2c3
Revises: b1a2c3d4e5f8
Create Date: 2026-10-19

Two additive tables, no data migration. `shelves` is unique on
`(tenant_id, name)` (exact match; the service adds the case-insensitive
check). `shelf_jobs` is the many-to-many membership with a composite primary
key, so a job is on a shelf at most once. Downgrade drops both; jobs are
untouched either way — that is the point of the design
(`docs/plans/m1-shelves.md`).
"""
import sqlalchemy as sa
from alembic import op

revision = "d8e9f0a1b2c3"
down_revision = "b1a2c3d4e5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shelves",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(20), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name", name="uq_shelves_tenant_name"),
    )
    op.create_index("ix_shelves_tenant_id", "shelves", ["tenant_id"])

    op.create_table(
        "shelf_jobs",
        sa.Column(
            "shelf_id",
            sa.String(36),
            sa.ForeignKey("shelves.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("added_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_shelf_jobs_job_id", "shelf_jobs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_shelf_jobs_job_id", table_name="shelf_jobs")
    op.drop_table("shelf_jobs")
    op.drop_index("ix_shelves_tenant_id", table_name="shelves")
    op.drop_table("shelves")
