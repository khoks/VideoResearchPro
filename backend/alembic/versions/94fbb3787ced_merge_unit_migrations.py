"""merge unit migrations

Revision ID: 94fbb3787ced
Revises: 7a1b2c3d4e5f, 7a1c9e3b4f20, a1b2c3d4e5f6, a1f2c3d4e5b6, b1c2d3e4f5a6
Create Date: 2026-04-19 14:21:28.448661

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '94fbb3787ced'
down_revision: Union[str, None] = ('7a1b2c3d4e5f', '7a1c9e3b4f20', 'a1b2c3d4e5f6', 'a1f2c3d4e5b6', 'b1c2d3e4f5a6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
