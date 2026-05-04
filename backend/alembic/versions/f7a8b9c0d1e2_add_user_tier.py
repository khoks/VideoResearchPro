"""Add tier column to users (E-5.2 subscription tier gating)

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-05-04 17:00:00.000000

Per [E-5.2 in initiatives.md](docs/initiatives.md#e-52--subscription-tier-gating)
and [saas-roadmap.md](docs/saas-roadmap.md), every user gets a ``tier`` column
that drives feature-gating + quota allocation. Self-host installs default
everyone to ``free``; operators may manually upgrade users (SQL UPDATE) to
``pro`` or ``studio``. SaaS deployment will set this from the billing
service.

The migration is purely additive:
- Adds ``users.tier String(16) NOT NULL DEFAULT 'free'`` — every existing
  row inherits the default.
- No index needed; the column is read on every authenticated request via
  the User row that's already loaded by ``get_current_user``.

The ``server_default='free'`` is what makes existing rows valid under the
NOT NULL constraint without a separate backfill step.

**Reversible:** ``downgrade()`` drops the column.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "tier",
            sa.String(length=16),
            nullable=False,
            server_default="free",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "tier")
