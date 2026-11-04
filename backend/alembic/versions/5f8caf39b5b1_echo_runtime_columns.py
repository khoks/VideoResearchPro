"""Echo runtime columns: a refresh claim, an edited fact's origin, a wider draft model

Revision ID: 5f8caf39b5b1
Revises: 6d5b3d5aa6fa
Create Date: 2026-11-04

Three small changes from one PR:

* ``echo_connector_credentials.refresh_claim`` and ``refresh_claimed_at``
  (T-3.2.1.12): the lease that lets one reader at a time spend a refresh
  token. Additive, nullable.
* ``personal_context.edited_from`` (T-3.2.1.11): on a derived row the user
  edited, the source it replaced, so deleting it still leaves a tombstone.
  Additive, nullable; a row edited before this has lost that fact.
* ``echo_drafts.model`` from 64 to 128 characters (T-3.4.1.10), matching
  ``echo_voice_tests.model`` and ``user_llm_overrides.model``. SQLite does not
  enforce the length, but it rebuilds the table in batch mode so the declared
  type matches the model; the index on the table is carried across.
"""
import sqlalchemy as sa
from alembic import op

revision = "5f8caf39b5b1"
down_revision = "6d5b3d5aa6fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("echo_connector_credentials") as batch:
        batch.add_column(sa.Column("refresh_claim", sa.String(36), nullable=True))
        batch.add_column(sa.Column("refresh_claimed_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("personal_context") as batch:
        batch.add_column(sa.Column("edited_from", sa.String(64), nullable=True))
    with op.batch_alter_table("echo_drafts") as batch:
        batch.alter_column("model", existing_type=sa.String(64), type_=sa.String(128), existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("echo_drafts") as batch:
        batch.alter_column("model", existing_type=sa.String(128), type_=sa.String(64), existing_nullable=True)
    with op.batch_alter_table("personal_context") as batch:
        batch.drop_column("edited_from")
    with op.batch_alter_table("echo_connector_credentials") as batch:
        batch.drop_column("refresh_claimed_at")
        batch.drop_column("refresh_claim")
