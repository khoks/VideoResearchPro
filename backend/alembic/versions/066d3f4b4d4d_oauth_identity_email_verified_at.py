"""oauth_identities.email_verified_at — when the provider vouched for the email (T-5.4.10)

Revision ID: 066d3f4b4d4d
Revises: e5a9c3d7b2f4
Create Date: 2026-10-25

Additive, nullable. A first OAuth link now needs a provider-verified email
(D-042 option B'), and the link records when the provider vouched. Existing
rows stay NULL: they were linked before T-5.4.10, when nothing checked, so a
later audit can tell the two apart without comparing dates.
"""
import sqlalchemy as sa
from alembic import op

revision = "066d3f4b4d4d"
down_revision = "e5a9c3d7b2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("oauth_identities") as batch:
        batch.add_column(sa.Column("email_verified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("oauth_identities") as batch:
        batch.drop_column("email_verified_at")
