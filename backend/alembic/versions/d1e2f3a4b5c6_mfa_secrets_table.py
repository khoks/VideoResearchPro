"""T-5.4.6 MFA / TOTP — mfa_secrets table

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-05-05 12:00:00.000000

Per [E-5.4 in initiatives.md](docs/initiatives.md#e-54--auth-hardening),
this migration adds the `mfa_secrets` table — one row per user when
MFA is enrolled. The TOTP secret is encrypted at rest via the same
Fernet key used for BYOK credentials (`BYOK_ENCRYPTION_KEY`).

**Reversible:** ``downgrade()`` drops the table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mfa_secrets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            nullable=False,
            unique=True,
        ),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "recovery_codes_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_mfa_secrets_user_id",
        "mfa_secrets",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_mfa_secrets_user_id", table_name="mfa_secrets")
    op.drop_table("mfa_secrets")
