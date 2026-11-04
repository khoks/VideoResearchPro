"""documents.language_mix — the per-document language profile (T-1.16.1.7)

Revision ID: 0253eef57358
Revises: 066d3f4b4d4d
Create Date: 2026-11-03

`code_mixing_service.profile_transcript` measures a source's primary language
of communication, the script its non-English words are written in, their
share and the quote form, once per chunking. Until now that profile lived
only in Chroma chunk metadata (`code_mix_*`), so a page that wanted to show a
source's language had to read Chroma, and a document chunked before S-1.16.2
had no profile anywhere. This column holds the same profile as JSON; every
chunking path writes it, and `scripts/backfill_language_mix.py` computes it
for older documents from their cached text, without an LLM.

Additive and nullable: NULL means "not profiled yet".
"""
import sqlalchemy as sa
from alembic import op

revision = "0253eef57358"
down_revision = "066d3f4b4d4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("language_mix", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("language_mix")
