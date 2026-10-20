"""activity_events + Echo connector grants, credentials and OAuth states (S-3.2.1)

Revision ID: e5773663cb2d
Revises: 7c1d9e3a5b42
Create Date: 2026-10-19

The connector runtime's storage (Domain 2). ``activity_events`` is idempotent
per ``(tenant_id, connector, external_id)``. Grants are part of the user's
archive; credentials and pending OAuth states are erased with the brain but
never exported (``echo_privacy_service.ECHO_SECRET_TABLES``).
"""
import sqlalchemy as sa
from alembic import op

revision = "e5773663cb2d"
down_revision = "7c1d9e3a5b42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("connector", sa.String(48), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("linked_document_id", sa.String(36), nullable=True),
        sa.Column("embedding_id", sa.String(64), nullable=True),
        sa.UniqueConstraint("tenant_id", "connector", "external_id", name="uq_activity_events_external"),
    )
    op.create_index(
        "ix_activity_events_user_connector_time", "activity_events", ["user_id", "connector", "occurred_at"]
    )
    op.create_index("ix_activity_events_tenant_time", "activity_events", ["tenant_id", "occurred_at"])

    op.create_table(
        "echo_connector_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connector", sa.String(48), nullable=False),
        sa.Column("consent_version", sa.String(32), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("account_label", sa.String(255), nullable=True),
        sa.Column("scopes", sa.String(500), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("backfilled_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("cursor_json", sa.Text(), nullable=True),
        sa.Column("last_counts_json", sa.Text(), nullable=True),
        sa.UniqueConstraint("tenant_id", "connector", name="uq_echo_connector_grants"),
    )

    op.create_table(
        "echo_connector_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connector", sa.String(48), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "connector", name="uq_echo_connector_credentials"),
    )

    op.create_table(
        "echo_connector_oauth_states",
        sa.Column("state", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connector", sa.String(48), nullable=False),
        sa.Column("code_verifier", sa.String(256), nullable=False),
        sa.Column("redirect_uri", sa.String(500), nullable=False),
        sa.Column("consent_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_echo_connector_oauth_states_tenant_id", "echo_connector_oauth_states", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_echo_connector_oauth_states_tenant_id", table_name="echo_connector_oauth_states")
    op.drop_table("echo_connector_oauth_states")
    op.drop_table("echo_connector_credentials")
    op.drop_table("echo_connector_grants")
    op.drop_index("ix_activity_events_tenant_time", table_name="activity_events")
    op.drop_index("ix_activity_events_user_connector_time", table_name="activity_events")
    op.drop_table("activity_events")
