"""newsletter_subscriptions + newsletter_sends (S-6.4.2)

Revision ID: 3e03de05cc5f
Revises: 7c1d9e3a5b42
Create Date: 2026-10-20

One digest subscription per reader, and a sends ledger whose unique
(subscription_id, period_key) makes scheduled delivery idempotent: the row is
inserted before an issue is generated, so a second dispatch for the same
period does nothing. Additive.
"""
import sqlalchemy as sa
from alembic import op

revision = "3e03de05cc5f"
down_revision = "7c1d9e3a5b42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "newsletter_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("cadence_json", sa.Text(), nullable=False),
        sa.Column("sections_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_issue_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_newsletter_subscriptions_tenant_id", "newsletter_subscriptions", ["tenant_id"], unique=True)
    op.create_table(
        "newsletter_sends",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subscription_id", sa.String(36), sa.ForeignKey("newsletter_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_key", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("output_id", sa.String(36), nullable=True),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("subscription_id", "period_key", name="uq_newsletter_sends_period"),
    )
    op.create_index("ix_newsletter_sends_subscription_id", "newsletter_sends", ["subscription_id"])


def downgrade() -> None:
    op.drop_index("ix_newsletter_sends_subscription_id", table_name="newsletter_sends")
    op.drop_table("newsletter_sends")
    op.drop_index("ix_newsletter_subscriptions_tenant_id", table_name="newsletter_subscriptions")
    op.drop_table("newsletter_subscriptions")
