"""outputs: celery_task_id + progress columns — generation moves to the worker (S-6.7.1)

Revision ID: 72d7e46ef057
Revises: a3b4c5d6e7f9
Create Date: 2026-10-19

`POST /author/outputs` used to generate inside the request. Generation now
runs in the Celery `generate_output` task on the owner's tier queue, so the
row needs the task id (for cancel) and the progress the worker publishes on
`job_progress:{output_id}` (for a page opened after the fact). Additive;
existing rows read as task-less with 0 % progress.
"""
import sqlalchemy as sa
from alembic import op

revision = "72d7e46ef057"
down_revision = "a3b4c5d6e7f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("outputs") as batch:
        batch.add_column(sa.Column("celery_task_id", sa.String(50), nullable=True))
        batch.add_column(
            sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("progress_message", sa.String(500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("outputs") as batch:
        batch.drop_column("progress_message")
        batch.drop_column("progress_pct")
        batch.drop_column("celery_task_id")
