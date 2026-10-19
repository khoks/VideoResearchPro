"""Echo shares inbox + tenant_id on personal_context (S-3.7.1)

Revision ID: 007c708bb890
Revises: a3b4c5d6e7f9
Create Date: 2026-10-19

The first new Echo table. ``shares_inbox`` holds everything the user forwards
to Echo (Domain 5). The same revision gives ``personal_context`` the
``tenant_id`` every user-scoped table carries, backfilled ``= user_id``
(self-host: a tenant is a user), because the full Echo export and delete
that ship with this table key on it.
"""
from alembic import op
import sqlalchemy as sa

revision = "007c708bb890"
down_revision = "a3b4c5d6e7f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shares_inbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("surface", sa.String(32), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("raw_payload_json", sa.Text(), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("user_annotation", sa.Text(), nullable=True),
        sa.Column("author_is_tenant", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("processing_state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("derived_fact_ids_json", sa.Text(), nullable=True),
        sa.Column("derived_signal_ids_json", sa.Text(), nullable=True),
        sa.Column("linked_document_id", sa.String(36), nullable=True),
        sa.Column("embedding_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_shares_inbox_tenant_received", "shares_inbox", ["tenant_id", "received_at"]
    )
    op.create_index(
        "ix_shares_inbox_tenant_state", "shares_inbox", ["tenant_id", "processing_state"]
    )

    with op.batch_alter_table("personal_context") as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(36), nullable=True))
    op.execute("UPDATE personal_context SET tenant_id = user_id WHERE tenant_id IS NULL")
    with op.batch_alter_table("personal_context") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(36), nullable=False)
        batch.create_index("ix_personal_context_tenant_id", ["tenant_id"])


def downgrade() -> None:
    with op.batch_alter_table("personal_context") as batch:
        batch.drop_index("ix_personal_context_tenant_id")
        batch.drop_column("tenant_id")
    op.drop_index("ix_shares_inbox_tenant_state", table_name="shares_inbox")
    op.drop_index("ix_shares_inbox_tenant_received", table_name="shares_inbox")
    op.drop_table("shares_inbox")
