"""Backfill tenant_id on user-scoped tables (E-5.1 phase 2a)

Revision ID: b2c3d4e5f6a7
Revises: d5e6f7a8b9c0
Create Date: 2026-05-04 14:00:00.000000

Per phase 2 of the [E-5.1 audit doc](docs/saas-tenant-id-audit.md),
this migration sets ``tenant_id`` on every existing row in the four
user-scoped tables (jobs / qa_exchanges / library_qa_exchanges /
qa_history_exchanges) using the **first user in `users`** as the
attribution target.

**Why first-user.** Existing self-host instances have N users sharing
one set of data; the migration can't reconstruct which user
originally created which row. The pragmatic fix is to attribute
everything to one user (typically the operator who set up the
instance) and let other users re-create their data going forward.
The audit doc's risk-3 captures this as the MVP-acceptable failure
mode.

If `users` is empty (a fresh install with no users registered yet),
the migration is a no-op — no rows to backfill, no users to
attribute to. New rows will tag tenant_id correctly via the code-
side changes shipping alongside this migration.

**No NOT NULL flip yet.** Phase 2b (separate future PR) flips the
columns to NOT NULL after operators have had time to run this and
verify their data attribution is correct. The "graceful single-
tenant" behavior continues until phase 2b.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BACKFILL_TABLES = (
    "jobs",
    "qa_exchanges",
    "library_qa_exchanges",
    "qa_history_exchanges",
)


def upgrade() -> None:
    bind = op.get_bind()
    # First user (by created_at) — the operator on most self-host
    # setups. ``LIMIT 1`` works on every supported dialect; for a
    # multi-user prod instance the operator can override the
    # attribution by manually updating tenant_id post-migration.
    first_user_row = bind.execute(
        text("SELECT id FROM users ORDER BY created_at ASC LIMIT 1")
    ).fetchone()
    if first_user_row is None:
        # Fresh install — no users yet, no rows to backfill.
        # New rows will tag tenant_id correctly via the code-side
        # changes shipping alongside this migration.
        return
    first_user_id = first_user_row[0]

    for table in _BACKFILL_TABLES:
        # `:tenant_id` parameter binding works across SQLite + Postgres.
        bind.execute(
            text(f"UPDATE {table} SET tenant_id = :tenant_id WHERE tenant_id IS NULL"),
            {"tenant_id": first_user_id},
        )


def downgrade() -> None:
    # Revert: clear tenant_id on every row in the affected tables.
    # We can't selectively un-backfill (the migration didn't record
    # which rows it touched), but since phase 1 didn't have
    # NOT NULL, NULL is a valid state.
    bind = op.get_bind()
    for table in _BACKFILL_TABLES:
        bind.execute(text(f"UPDATE {table} SET tenant_id = NULL"))
