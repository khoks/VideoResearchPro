"""Onboarding state on users (S-8.10.1 / M10)

Revision ID: e8667092c208
Revises: c5ee7a568ef8
Create Date: 2026-10-19 21:00:00.000000

The first-run wizard at ``/welcome`` keeps its progress on the server so it
survives devices and browser resets (plan: docs/plans/m10-onboarding.md):

- ``users.onboarded_at`` DATETIME NULL — set when the wizard is finished.
- ``users.onboarding_state_json`` TEXT NULL — ``{step, choices, dismissed,
  started_at, completed_at, dismissed_at}``; NULL until the wizard is first
  touched.

Purely additive: existing rows keep NULL in both, which the API reads as
"never started". Existing accounts that already have runs are not sent to
the wizard (``onboarding_service.should_onboard``), so no backfill.

**Reversible:** ``downgrade()`` drops both columns.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8667092c208"
down_revision: Union[str, Sequence[str], None] = "c5ee7a568ef8"  # re-parented onto S-6.7.3 (merged first)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("onboarded_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("onboarding_state_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("onboarding_state_json")
        batch.drop_column("onboarded_at")
