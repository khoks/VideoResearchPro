"""Add tenant_id columns to user-scoped tables (E-5.1 phase 1)

Revision ID: d5e6f7a8b9c0
Revises: f3456789cdef
Create Date: 2026-05-04 12:00:00.000000

Per `docs/saas-tenant-id-audit.md`, this is the first concrete schema
step toward multi-tenant readiness for SaaS. We add a NULLABLE
``tenant_id`` column to each of the four user-scoped tables identified
in the audit:

- ``jobs``
- ``qa_exchanges``
- ``library_qa_exchanges``
- ``qa_history_exchanges``

NULLABLE because:

1. Existing rows don't have a tenant — we don't want a migration that
   needs to backfill before it can land. The backfill is phase 2.
2. Any code path that does INSERT before phase 2 ships will simply
   write NULL — the rows are still readable / writable; they just
   sit in the conceptual "global tenant" until phase 2's NOT NULL
   constraint forces every writer to set it explicitly.

Plus an index on ``tenant_id`` for each table so the eventual phase-2
query updates (``WHERE tenant_id = ?``) get fast lookups from the
start.

**No data is moved by this migration.** Existing rows keep their
current visibility (shared globally across all authenticated users).
That's the same single-tenant behaviour the app has today — phase 1
is purely additive groundwork.

**Reversible:** ``downgrade()`` drops the columns + indexes. Safe to
roll back even if some new rows have written non-NULL ``tenant_id``;
their values are simply discarded.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "f3456789cdef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Per E-5.1 audit, these are the four user-scoped tables.
_TARGET_TABLES = (
    "jobs",
    "qa_exchanges",
    "library_qa_exchanges",
    "qa_history_exchanges",
)


def upgrade() -> None:
    for table in _TARGET_TABLES:
        op.add_column(
            table,
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
        )
        op.create_index(
            f"ix_{table}_tenant_id",
            table,
            ["tenant_id"],
            unique=False,
        )


def downgrade() -> None:
    # Reverse order — drop indexes before columns so SQLite's batch
    # mode handles the rebuild cleanly.
    for table in _TARGET_TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
