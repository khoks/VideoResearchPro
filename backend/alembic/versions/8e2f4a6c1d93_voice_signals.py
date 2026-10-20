"""voice_signals — Echo voice and personality signals (S-3.3.1 / E-3.3)

Revision ID: 8e2f4a6c1d93
Revises: 7c1d9e3a5b42
Create Date: 2026-10-19

Additive. One row per signal, tenant-keyed, registered in Echo's privacy
registry (D-089) so the whole-brain export and delete cover it. Downgrade
drops the table.
"""
import sqlalchemy as sa
from alembic import op

revision = "8e2f4a6c1d93"
down_revision = "7c1d9e3a5b42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("signal_type", sa.String(32), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_key", sa.String(300), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("examples_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("register", sa.String(16), nullable=True),
        sa.Column("derived_from", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("origin", sa.String(16), nullable=False, server_default="user"),
        sa.Column("consent_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("suppressed_at", sa.DateTime(), nullable=True),
        sa.Column("suppressed_reason", sa.String(16), nullable=True),
    )
    op.create_index("ix_voice_signals_tenant_type", "voice_signals", ["tenant_id", "signal_type"])
    op.create_index("ix_voice_signals_merge_key", "voice_signals", ["tenant_id", "signal_type", "value_key", "language"])


def downgrade() -> None:
    op.drop_index("ix_voice_signals_merge_key", table_name="voice_signals")
    op.drop_index("ix_voice_signals_tenant_type", table_name="voice_signals")
    op.drop_table("voice_signals")
