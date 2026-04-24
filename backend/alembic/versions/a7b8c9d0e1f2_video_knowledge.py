"""add knowledge extraction columns to videos

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-22 23:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add on-demand knowledge extraction artifacts to `videos`.

    Three nullable columns persist the output of the knowledge agent:
      - extracted_knowledge_json: structured {topics, concepts, events, facts}
      - knowledge_report_md: synthesized Markdown knowledge document
      - knowledge_extracted_at: timestamp of the last successful extraction
    """
    with op.batch_alter_table("videos") as batch_op:
        batch_op.add_column(sa.Column("extracted_knowledge_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("knowledge_report_md", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("knowledge_extracted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("videos") as batch_op:
        batch_op.drop_column("knowledge_extracted_at")
        batch_op.drop_column("knowledge_report_md")
        batch_op.drop_column("extracted_knowledge_json")
