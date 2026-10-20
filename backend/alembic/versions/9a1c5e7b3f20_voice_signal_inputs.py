"""voice_signal_inputs — the texts signal extraction has read (S-3.3.2 / E-3.3)

Revision ID: 9a1c5e7b3f20
Revises: e5773663cb2d
Create Date: 2026-10-19

Additive. One row per input the extraction read, with the hash of the
version it read and its stylometric profile. Registered in Echo's privacy
registry (D-089) so the whole-brain export and delete cover it. Downgrade
drops the table.
"""
import sqlalchemy as sa
from alembic import op

revision = "9a1c5e7b3f20"
down_revision = "e5773663cb2d"  # re-parented onto S-3.2.1 (merged first)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_signal_inputs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("source_ref", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("llm_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("features_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("processed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "source_ref", name="uq_voice_signal_inputs_ref"),
    )
    op.create_index("ix_voice_signal_inputs_tenant_id", "voice_signal_inputs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_voice_signal_inputs_tenant_id", table_name="voice_signal_inputs")
    op.drop_table("voice_signal_inputs")
