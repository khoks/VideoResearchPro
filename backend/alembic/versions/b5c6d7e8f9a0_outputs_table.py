"""I-6 Author Studio foundation — outputs table

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-05-05 17:00:00.000000

Per [I-6 in initiatives.md](docs/initiatives.md#i-6--author-studio-output-generation-l2),
this migration adds the foundation table for L2 Author Studio — one
row per generated artifact (book / site / deck / newsletter / reel).

**Reversible:** ``downgrade()`` drops the table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outputs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "source_ids_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "parameters_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_path", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_outputs_user_id", "outputs", ["user_id"])
    op.create_index("ix_outputs_kind", "outputs", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_outputs_kind", table_name="outputs")
    op.drop_index("ix_outputs_user_id", table_name="outputs")
    op.drop_table("outputs")
