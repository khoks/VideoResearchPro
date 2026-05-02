"""Add source_types JSON column to jobs

Revision ID: f3456789cdef
Revises: e2345678abcd
Create Date: 2026-05-02 12:00:00.000000

S-1.5.11 wiring step: lets a topic job declare which `source_type`s
its search dispatches across. Stored as a JSON-encoded string array
(e.g. ``'["video"]'``, ``'["video","reddit_post","hn_story"]'``).
NULL is interpreted as ``["video"]`` for back-compat with the
hundreds of jobs created before this column existed.

The orchestrator (``execute_topic_job``) reads this column to drive
``connector_dispatch.dispatch_search()`` once non-video source_types
are wired (T-1.5.11.4 + integration). Today's read path defaults
NULL → video-only so existing behaviour is unchanged.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f3456789cdef"
down_revision: Union[str, Sequence[str], None] = "e2345678abcd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("source_types_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("source_types_json")
