"""library_qa_exchanges.scope_json: what a library question was asked over (S-8.1.4)

Revision ID: cd4c5467506d
Revises: 0b90c419b558
Create Date: 2026-10-19

NULL is the whole library (every document the reader can see), which is what
every existing row was. A JSON object narrows it ({"shelf_id": ...}) or records
where the exchange came from ({"saved_search_id": ...}, M3); the shape is
documented in app/schemas/qa_scope.py. One history table stays one history
table, and the Q&A library index needs no change.
"""
import sqlalchemy as sa
from alembic import op

revision = "cd4c5467506d"
down_revision = "0b90c419b558"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("library_qa_exchanges") as batch:
        batch.add_column(sa.Column("scope_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("library_qa_exchanges") as batch:
        batch.drop_column("scope_json")
