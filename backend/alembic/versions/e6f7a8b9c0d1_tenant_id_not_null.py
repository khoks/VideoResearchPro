"""Tighten tenant_id to NOT NULL (E-5.1 phase 2c / T-5.1.2c)

Revision ID: e6f7a8b9c0d1
Revises: b2c3d4e5f6a7
Create Date: 2026-05-04 16:00:00.000000

Per the [E-5.1 phase 2c runbook](docs/migration-tenant-id-not-null.md)
and [D-038](docs/decisions.md#d-038--tenancy-retrofit-ships-in-four-phases-audit--additive--backfillwrites--reads--not-null-2026-05-04),
this is the **final** phase of the tenancy retrofit.

After phase 2a (PR #151) backfilled every existing row and phase 2b
(PR #152) made the read-side filter mandatory, every row in the four
user-scoped tables has ``tenant_id`` populated. This migration locks
that invariant in at the schema level by flipping ``nullable=False``.

**This migration assumes the operator has run the runbook**:

1. Pre-flight verified zero ``tenant_id IS NULL`` rows on each table.
2. Database backed up.
3. All writers stopped before applying.

If any NULL row remains when this runs, the underlying SQLite
``ALTER TABLE`` will abort with an integrity error. The runbook's
pre-flight check exists precisely to prevent that. **Operators who
apply this migration without running the pre-flight are taking the
risk knowingly.**

**Reversible:** ``downgrade()`` flips ``nullable=True`` back. The
backfilled values are preserved; only the constraint is loosened.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TARGET_TABLES = (
    "jobs",
    "qa_exchanges",
    "library_qa_exchanges",
    "qa_history_exchanges",
)


def upgrade() -> None:
    # SQLite emulates ALTER COLUMN by recreating the table; batch
    # mode wraps that for us. Each table is independently atomic.
    for table in _TARGET_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                "tenant_id",
                existing_type=sa.String(length=36),
                nullable=False,
            )


def downgrade() -> None:
    for table in _TARGET_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                "tenant_id",
                existing_type=sa.String(length=36),
                nullable=True,
            )
