"""run notes and source refusals (S-1.5.14)

Revision ID: 8e4b1f6c2a37
Revises: c62da1d081c6
Create Date: 2026-11-04

Two additive changes:

* ``jobs.run_notes_json``: what a run has to tell its reader about its sources
  and limits (``app/services/run_notes.py``). NULL for every existing run, and
  for any run with nothing to say.

* ``source_refusals``: one row per source type that answered 401 or 403, so
  the submit form stops offering it for a while
  (``app/services/source_refusal_service.py``). Empty to begin with.

**Reversible:** ``downgrade()`` drops the table and the column. The notes on
past runs go with it. Nothing else reads them.
"""
import sqlalchemy as sa
from alembic import op

revision = "8e4b1f6c2a37"
down_revision = "c62da1d081c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("run_notes_json", sa.Text(), nullable=True))
    op.create_table(
        "source_refusals",
        sa.Column("source_type", sa.String(length=32), primary_key=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=16), nullable=False),
        sa.Column("refused_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("source_refusals")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("run_notes_json")
