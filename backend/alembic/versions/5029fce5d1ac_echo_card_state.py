"""echo_card_state — the Echo panel's anticipation cards (S-3.8.2)

Revision ID: 5029fce5d1ac
Revises: b7e2c4a9d1f6
Create Date: 2026-10-20

What each card has shown and what the user did with it, per tenant and key,
for the pre-registered frequency cap and dismissal rule. Purely additive.
"""
from alembic import op
import sqlalchemy as sa

revision = "5029fce5d1ac"
down_revision = "b7e2c4a9d1f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "echo_card_state",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("shown_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_shown_on", sa.Date(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(), nullable=True),
        sa.Column("acted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "key", name="uq_echo_card_state_key"),
    )


def downgrade() -> None:
    op.drop_table("echo_card_state")
