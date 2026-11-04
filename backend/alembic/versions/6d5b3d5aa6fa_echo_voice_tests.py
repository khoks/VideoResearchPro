"""echo_voice_tests — the in-app voice test for speak as me (T-3.4.1.8)

Revision ID: 6d5b3d5aa6fa
Revises: a68953e57c63
Create Date: 2026-11-04

One row per "which of these did you write?" test taken on the Echo page:
the blinded pairs, the user's picks, the score. Registered in Echo's privacy
registry (D-089), so the whole-brain export carries it and the brain delete
removes it. A partial unique index holds one open test per tenant. Purely
additive; downgrade drops it.
"""
import sqlalchemy as sa
from alembic import op

revision = "6d5b3d5aa6fa"
down_revision = "a68953e57c63"
branch_labels = None
depends_on = None

OPEN = sa.text("status IN ('generating', 'ready')")


def upgrade() -> None:
    op.create_table(
        "echo_voice_tests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("pairs_total", sa.Integer(), nullable=False),
        sa.Column("pairs_built", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pairs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("key_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("picks_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("picked_own", sa.Integer(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_progress_at", sa.DateTime(), nullable=True),
        sa.Column("ready_at", sa.DateTime(), nullable=True),
        sa.Column("scored_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_echo_voice_tests_tenant_created", "echo_voice_tests", ["tenant_id", "created_at"])
    op.create_index(
        "uq_echo_voice_tests_one_open", "echo_voice_tests", ["tenant_id"], unique=True,
        sqlite_where=OPEN, postgresql_where=OPEN,
    )


def downgrade() -> None:
    op.drop_index("uq_echo_voice_tests_one_open", table_name="echo_voice_tests")
    op.drop_index("ix_echo_voice_tests_tenant_created", table_name="echo_voice_tests")
    op.drop_table("echo_voice_tests")
