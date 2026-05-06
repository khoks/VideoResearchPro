"""T-5.4.5 OAuth — oauth_states + oauth_identities tables

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-05-05 13:00:00.000000

Per [E-5.4 in initiatives.md](docs/initiatives.md#e-54--auth-hardening),
this migration adds two tables for OAuth 2.0 + PKCE flow:

- ``oauth_states`` — short-lived CSRF / PKCE state (10 min TTL).
- ``oauth_identities`` — long-lived link between a provider account
  and a Pratidhvani user. ``(provider, provider_user_id)`` is unique.

**Reversible:** ``downgrade()`` drops both tables.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_states",
        sa.Column("state", sa.String(length=64), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.String(length=512), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "oauth_identities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column(
            "provider_user_id", sa.String(length=128), nullable=False
        ),
        sa.Column("provider_email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_oauth_identities_provider_user",
        ),
    )
    op.create_index(
        "ix_oauth_identities_user_id",
        "oauth_identities",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_oauth_identities_user_id", table_name="oauth_identities"
    )
    op.drop_table("oauth_identities")
    op.drop_table("oauth_states")
