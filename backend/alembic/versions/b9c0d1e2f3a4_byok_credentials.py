"""E-5.6 BYOK LLM keys foundation — user_credentials table

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-05-04 19:00:00.000000

Per [E-5.6 in initiatives.md](docs/initiatives.md#e-56--background-job-isolation),
this migration ships the foundation for per-user BYOK LLM keys —
power users on the Studio tier can route their LLM calls to their
own provider account rather than the install-wide env-var key.

Encryption-at-rest: the secrets are stored as Fernet ciphertext;
the plaintext is never persisted. Decryption only happens at the
LLM-call site.

Schema:
- ``user_credentials(id, user_id, provider, encrypted_secret, label,
  created_at, updated_at)``
- Unique on ``(user_id, provider)`` — at most one credential per
  user per provider; PUT-style overwrite.
- Index on ``user_id`` for the per-user listing endpoint.

**Reversible:** ``downgrade()`` drops the table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "provider", name="uq_user_credentials_user_provider"
        ),
    )
    op.create_index(
        "ix_user_credentials_user_id",
        "user_credentials",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_credentials_user_id", table_name="user_credentials")
    op.drop_table("user_credentials")
