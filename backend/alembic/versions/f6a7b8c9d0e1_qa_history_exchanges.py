"""add qa_history_exchanges table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-23 06:17:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'qa_history_exchanges',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('references_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('answer_language', sa.String(length=10), nullable=False, server_default='en'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_qa_history_exchanges_created_at',
        'qa_history_exchanges',
        ['created_at'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_qa_history_exchanges_created_at',
        table_name='qa_history_exchanges',
    )
    op.drop_table('qa_history_exchanges')
