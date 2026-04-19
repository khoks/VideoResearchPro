"""add ix_videos_job_id index

Revision ID: a1f2c3d4e5b6
Revises: 23670b97ba39
Create Date: 2026-04-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1f2c3d4e5b6'
down_revision: Union[str, None] = '23670b97ba39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Index on videos.job_id accelerates the very common per-job video
    # lookups performed by /jobs/{id}/videos, approval flows, and the
    # Celery orchestrator.
    op.create_index('ix_videos_job_id', 'videos', ['job_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_videos_job_id', table_name='videos')
