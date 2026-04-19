"""add transcript_cache table

Revision ID: a1b2c3d4e5f6
Revises: 23670b97ba39
Create Date: 2026-04-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '23670b97ba39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'transcript_cache',
        sa.Column('video_id', sa.String(length=20), nullable=False),
        sa.Column('segments_json', sa.Text(), nullable=False),
        sa.Column('language', sa.String(length=10), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('video_id'),
    )


def downgrade() -> None:
    op.drop_table('transcript_cache')
