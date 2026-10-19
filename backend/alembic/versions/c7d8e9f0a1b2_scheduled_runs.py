"""scheduled_runs — the scheduler tick's table (S-8.3.1 / M3)

Revision ID: c7d8e9f0a1b2
Revises: b1a2c3d4e5f8
Create Date: 2026-10-19

First scheduled work in the app. One row per (kind, target_id) with a human
cadence (daily / weekly / monthly / every N seconds, never cron) and a UTC
``next_run_at``. The Celery beat entry ``scheduler.tick`` claims due rows
with a short lease (``claimed_at``) and dispatches each kind's task on the
owning tenant's tier queue. Saved searches (S-8.3.2), the newsletter (E-6.4)
and Echo syncs (S-3.2.1) add rows; nothing writes here yet.

Purely additive; no backfill.
"""
import sqlalchemy as sa
from alembic import op

revision = "c7d8e9f0a1b2"
down_revision = "b1a2c3d4e5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("cadence_json", sa.Text(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kind", "target_id", name="uq_scheduled_runs_kind_target"),
    )
    op.create_index("ix_scheduled_runs_tenant_id", "scheduled_runs", ["tenant_id"])
    op.create_index("ix_scheduled_runs_kind", "scheduled_runs", ["kind"])
    op.create_index("ix_scheduled_runs_next_run_at", "scheduled_runs", ["next_run_at"])
    op.create_index("ix_scheduled_runs_due", "scheduled_runs", ["enabled", "next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_runs_due", table_name="scheduled_runs")
    op.drop_index("ix_scheduled_runs_next_run_at", table_name="scheduled_runs")
    op.drop_index("ix_scheduled_runs_kind", table_name="scheduled_runs")
    op.drop_index("ix_scheduled_runs_tenant_id", table_name="scheduled_runs")
    op.drop_table("scheduled_runs")
