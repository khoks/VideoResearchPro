"""echo_imports + shares_inbox.import_id / occurred_at (S-3.7.5)

Revision ID: 509a4efd9319
Revises: 7c1d9e3a5b42
Create Date: 2026-10-19

An import (a WhatsApp chat, a Google Takeout archive) writes many shares at
once. ``echo_imports`` records each import so the user can list and undo
them; ``shares_inbox.import_id`` ties every share to the import that wrote
it, and ``occurred_at`` keeps when the message or note was written, which is
not when it landed in the inbox. Purely additive: existing shares keep both
columns NULL.
"""
from alembic import op
import sqlalchemy as sa

revision = "509a4efd9319"
down_revision = "7c1d9e3a5b42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "echo_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("importer", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=True),
        sa.Column("counts_json", sa.Text(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_echo_imports_tenant_created", "echo_imports", ["tenant_id", "created_at"])
    with op.batch_alter_table("shares_inbox") as batch:
        batch.add_column(sa.Column("import_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("occurred_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_shares_inbox_tenant_import", ["tenant_id", "import_id"])


def downgrade() -> None:
    with op.batch_alter_table("shares_inbox") as batch:
        batch.drop_index("ix_shares_inbox_tenant_import")
        batch.drop_column("occurred_at")
        batch.drop_column("import_id")
    op.drop_index("ix_echo_imports_tenant_created", table_name="echo_imports")
    op.drop_table("echo_imports")
