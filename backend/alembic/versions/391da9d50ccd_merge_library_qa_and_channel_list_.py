"""merge library_qa and channel_list_resolved heads

Revision ID: 391da9d50ccd
Revises: c1d2e3f4a5b6, d4e5f6a7b8c9
Create Date: 2026-04-19 18:51:48.601981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '391da9d50ccd'
down_revision: Union[str, None] = ('c1d2e3f4a5b6', 'd4e5f6a7b8c9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
