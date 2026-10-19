"""Search index — FTS5 trigram tables and triggers, when SQLite has FTS5 (S-8.2.1 / M2)

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-10-19

Five virtual tables (`fts_documents`, `fts_jobs`, `fts_channels`, `fts_qa`,
`fts_knowledge`) kept current by AFTER INSERT / UPDATE / DELETE triggers on
their base tables, populated from existing rows on creation. All DDL lives
in `app/services/search_service.py` (`ensure_index` / `drop_index`), which
the FastAPI lifespan also calls, so a Python upgrade that gains FTS5 after
this revision ran still gets the tables at the next boot.

**Conditional.** When the linked SQLite lacks FTS5 or its trigram tokenizer
(some Linux distro Pythons), the probe fails, nothing is created, a warning
is logged and the app searches with LIKE. The migration never fails for
that reason. The tables are not SQLAlchemy models; `schema_init_service`
ignores the `fts_` prefix when comparing the live DB to the ORM.
"""
import logging

from alembic import op

revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    from app.services import search_service

    backend = search_service.ensure_index(op.get_bind())
    if backend != search_service.BACKEND_FTS5:
        logger.warning(
            "search: FTS5 unavailable in this SQLite build; no search tables created "
            "(the app falls back to LIKE scans)."
        )


def downgrade() -> None:
    from app.services import search_service

    search_service.drop_index(op.get_bind())
