"""job_search_candidates — persist the full search candidate pool (S-1.14.6)

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a8
Create Date: 2026-07-30

``rank_and_curate`` discarded every candidate it rejected, which made
selection quality unmeasurable (D-055 had to audit the picks instead of
re-ranking). This stores the whole pool with a ``selected`` flag.
"""
import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b9"
down_revision = "b2c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_search_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("video_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("channel_name", sa.String(255)),
        sa.Column("channel_id", sa.String(64)),
        sa.Column("published_at", sa.String(64)),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("payload_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_job_search_candidates_job_id", "job_search_candidates", ["job_id"])
    op.create_index(
        "ix_job_search_candidates_job_selected", "job_search_candidates", ["job_id", "selected"]
    )


def downgrade() -> None:
    op.drop_index("ix_job_search_candidates_job_selected", table_name="job_search_candidates")
    op.drop_index("ix_job_search_candidates_job_id", table_name="job_search_candidates")
    op.drop_table("job_search_candidates")
