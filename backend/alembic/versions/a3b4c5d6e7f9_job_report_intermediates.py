"""job_report_intermediates — persist map/reduce intermediates (S-1.14.6)

Revision ID: a3b4c5d6e7f9
Revises: f1a2b3c4d5e6
Create Date: 2026-10-19

The report pipeline discarded its per-batch map extractions and its reduced
dataset once compose ran, so stage quality could only be measured by
replaying a job's inputs. This stores both, keyed to the job and grouped by
report run. Purely additive.
"""
import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7f9"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_report_intermediates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id", sa.String(36),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sub_index", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("notes_json", sa.Text(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_job_report_intermediates_job_id", "job_report_intermediates", ["job_id"]
    )
    op.create_index(
        "ix_job_report_intermediates_job_run_stage",
        "job_report_intermediates",
        ["job_id", "run_id", "stage"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_report_intermediates_job_run_stage", table_name="job_report_intermediates"
    )
    op.drop_index("ix_job_report_intermediates_job_id", table_name="job_report_intermediates")
    op.drop_table("job_report_intermediates")
