"""add library_qa_exchanges table

Revision ID: c1d2e3f4a5b6
Revises: 94fbb3787ced
Create Date: 2026-04-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = '94fbb3787ced'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'library_qa_exchanges',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('references_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('answer_language', sa.String(length=10), nullable=False, server_default='en'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_library_qa_exchanges_created_at',
        'library_qa_exchanges',
        ['created_at'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_library_qa_exchanges_created_at',
        table_name='library_qa_exchanges',
    )
    op.drop_table('library_qa_exchanges')
