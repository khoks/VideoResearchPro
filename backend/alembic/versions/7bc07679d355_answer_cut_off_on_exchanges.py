"""answer_cut_off on the exchange tables: a cut answer stays noted (T-1.15.4.8)

Revision ID: 7bc07679d355
Revises: 869754146393
Create Date: 2026-11-05

One additive, nullable column on each table a Q&A card reads from:
``qa_exchanges``, ``library_qa_exchanges`` and ``qa_history_exchanges``.

Nothing is backfilled. Whether an old answer was cut was never recorded, so NULL
is "unknown": it shows no note, and it never reads as "not cut".

**Reversible:** ``downgrade()`` drops the columns, and with them what the check
found. The answers stay. On SQLite it rebuilds each table, which takes the search
triggers on these tables with it, as with any batch ``drop_column`` here; the
API's next start puts them back (``search_service.ensure_index_for_url``).
"""
import sqlalchemy as sa
from alembic import op

revision = "7bc07679d355"
down_revision = "869754146393"
branch_labels = None
depends_on = None

_TABLES = ("qa_exchanges", "library_qa_exchanges", "qa_history_exchanges")


def upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("answer_cut_off", sa.Boolean(), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("answer_cut_off")
