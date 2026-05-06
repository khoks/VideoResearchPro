"""I-3 Echo foundation — personal_context table

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-05-05 16:00:00.000000

Per [E-3.1 in initiatives.md](docs/initiatives.md#e-31--personal-context-store-schema),
this migration adds the foundation table for the Echo personal-brain
initiative — per-user identity / interests / hobbies / work / talents
/ skills / personality / life events / locations / routines.

Distinct from the global `documents` table (which is sources content);
this is **about-the-user** data with strict per-user scoping.

**Reversible:** ``downgrade()`` drops the table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "personal_context",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "user_id",
            "kind",
            "key",
            name="uq_personal_context_user_kind_key",
        ),
    )
    op.create_index(
        "ix_personal_context_user_id", "personal_context", ["user_id"]
    )
    op.create_index(
        "ix_personal_context_kind", "personal_context", ["kind"]
    )


def downgrade() -> None:
    op.drop_index("ix_personal_context_kind", table_name="personal_context")
    op.drop_index("ix_personal_context_user_id", table_name="personal_context")
    op.drop_table("personal_context")
