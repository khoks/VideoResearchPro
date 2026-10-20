"""echo_drafts and echo_voice_gates — speak as me (S-3.4.1 / E-3.4)

Revision ID: b7e2c4a9d1f6
Revises: d3bc5b91fcce
Create Date: 2026-10-20

Additive. Both tables are registered in Echo's privacy registry (D-089), so
the whole-brain export carries them and the brain delete removes them.
Downgrade drops both.
"""
import sqlalchemy as sa
from alembic import op

revision = "b7e2c4a9d1f6"
down_revision = "d3bc5b91fcce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "echo_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("input_message", sa.Text(), nullable=False),
        sa.Column("audience", sa.String(200), nullable=True),
        sa.Column("register", sa.String(16), nullable=True),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("intent", sa.String(32), nullable=True),
        sa.Column("draft", sa.Text(), nullable=False),
        sa.Column("voice_match_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("citations_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("deviation_notes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("flags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("critique_rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("disclosure", sa.String(300), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("disclosure_kept", sa.Boolean(), nullable=True),
        sa.Column("feedback_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_echo_drafts_tenant_created", "echo_drafts", ["tenant_id", "created_at"])
    op.create_table(
        "echo_voice_gates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("pairs", sa.Integer(), nullable=False),
        sa.Column("picked_own_share", sa.Float(), nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_echo_voice_gates_tenant"),
    )


def downgrade() -> None:
    op.drop_table("echo_voice_gates")
    op.drop_index("ix_echo_drafts_tenant_created", table_name="echo_drafts")
    op.drop_table("echo_drafts")
