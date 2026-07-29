"""user_llm_overrides table (E-1.13)

Per-user (provider, model, reasoning) overrides keyed by LLM use case.

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a8"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_llm_overrides",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("use_case", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("reasoning", sa.String(length=16), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "use_case", name="uq_user_llm_override"),
    )
    op.create_index(
        "ix_user_llm_overrides_user_id", "user_llm_overrides", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_llm_overrides_user_id", table_name="user_llm_overrides")
    op.drop_table("user_llm_overrides")
