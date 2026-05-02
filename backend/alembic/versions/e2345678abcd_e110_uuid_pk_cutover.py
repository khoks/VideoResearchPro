"""E-1.10 UUID PK cutover (T-1.10.2 + .4 + .5)

Revision ID: e2345678abcd
Revises: d12345678901
Create Date: 2026-05-02 09:00:00.000000

E-1.10 hard cutover (D-017) — picks up where T-1.10.1
(``d12345678901``) left off. T-1.10.1 added the ``document_id`` UUID
column and backfilled it with one fresh UUID4 per existing row.

This migration retires the legacy ``video_id`` primary-key plumbing:

* ``documents.video_id`` loses its PRIMARY KEY constraint (column
  retained as a NULLABLE back-compat reading column — readers that
  still want the YouTube native ID can keep going via ``video_id``
  for video rows; ``source_id`` is the canonical platform-native
  identifier going forward and already mirrors ``video_id`` for
  every video row).
* ``documents.document_id`` becomes the new PRIMARY KEY.
* ``job_videos`` is renamed to ``job_documents`` and gets a new
  ``document_id`` column (FK → ``documents.document_id``) backfilled
  by JOIN on the existing ``video_id``. The composite PK becomes
  ``(job_id, document_id)``.
* ``transcript_cache`` gets a new ``document_id`` column (FK →
  ``documents.document_id``) backfilled by JOIN; ``document_id``
  becomes the new PK.

Why keep the legacy ``video_id`` columns instead of dropping them
outright? See the module docstring of ``app/models/document.py`` —
keeping the column lets us make surgical changes to *joins* without
simultaneously cascading through every reader of the YouTube native
ID. Full deletion lands in a follow-up E-2.6-style cleanup pass.

SQLite has no native ``ALTER TABLE`` for primary keys, foreign keys,
or NOT NULL constraints. We use the explicit table-rebuild pattern
(CREATE NEW + INSERT FROM OLD + DROP OLD + RENAME) for every PK
change in this migration; ``batch_alter_table`` works for additive
column changes but isn't reliable for full identity rewrites.

Reversibility: the ``downgrade()`` path runs the rebuilds in reverse
on a synthetic post-upgrade DB (T-1.10.8 round-trip test).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e2345678abcd"
down_revision: Union[str, Sequence[str], None] = "d12345678901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. job_videos → job_documents — full rebuild with new PK + FK.
    # ------------------------------------------------------------------
    # 1a: add document_id nullable so we can backfill.
    op.execute("ALTER TABLE job_videos ADD COLUMN document_id VARCHAR(36)")
    # 1b: backfill via JOIN.
    op.execute(
        """
        UPDATE job_videos
        SET document_id = (
            SELECT documents.document_id
            FROM documents
            WHERE documents.video_id = job_videos.video_id
        )
        """
    )
    # 1c: rebuild with new PK (job_id, document_id) + FK to documents.document_id,
    # rename to job_documents in the same step.
    op.execute(
        """
        CREATE TABLE job_documents (
            job_id VARCHAR(36) NOT NULL,
            document_id VARCHAR(36) NOT NULL,
            video_id VARCHAR(20),
            approved BOOLEAN NOT NULL,
            curated_at DATETIME NOT NULL,
            selection_reason TEXT,
            PRIMARY KEY (job_id, document_id),
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        INSERT INTO job_documents (job_id, document_id, video_id, approved, curated_at, selection_reason)
        SELECT job_id, document_id, video_id, approved, curated_at, selection_reason FROM job_videos
        """
    )
    op.execute("DROP TABLE job_videos")
    op.create_index("ix_job_documents_job_id", "job_documents", ["job_id"])
    op.create_index(
        "ix_job_documents_document_id", "job_documents", ["document_id"]
    )
    op.create_index("ix_job_documents_video_id", "job_documents", ["video_id"])

    # ------------------------------------------------------------------
    # 2. transcript_cache — add document_id, backfill, swap PK.
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE transcript_cache ADD COLUMN document_id VARCHAR(36)")
    op.execute(
        """
        UPDATE transcript_cache
        SET document_id = (
            SELECT documents.document_id
            FROM documents
            WHERE documents.video_id = transcript_cache.video_id
        )
        """
    )
    op.execute(
        """
        CREATE TABLE transcript_cache_new (
            document_id VARCHAR(36) NOT NULL PRIMARY KEY,
            video_id VARCHAR(20),
            segments_json TEXT NOT NULL,
            language VARCHAR(10) NOT NULL,
            fetched_at DATETIME NOT NULL,
            FOREIGN KEY(document_id) REFERENCES documents(document_id) ON DELETE CASCADE
        )
        """
    )
    # If a transcript_cache row's document_id couldn't be resolved
    # (orphaned cache entry) we drop it — the cache is regeneratable.
    op.execute(
        """
        INSERT INTO transcript_cache_new (document_id, video_id, segments_json, language, fetched_at)
        SELECT document_id, video_id, segments_json, language, fetched_at
        FROM transcript_cache
        WHERE document_id IS NOT NULL
        """
    )
    op.execute("DROP TABLE transcript_cache")
    op.execute("ALTER TABLE transcript_cache_new RENAME TO transcript_cache")

    # ------------------------------------------------------------------
    # 3. documents — swap PK from video_id to document_id.
    # ------------------------------------------------------------------
    op.drop_index("ix_documents_document_id", table_name="documents")
    op.execute(
        """
        CREATE TABLE documents_new (
            document_id VARCHAR(36) NOT NULL PRIMARY KEY,
            video_id VARCHAR(20),
            channel_id VARCHAR(50),
            title VARCHAR(500) NOT NULL,
            url VARCHAR(200) NOT NULL,
            thumbnail_url VARCHAR(500),
            duration_seconds INTEGER,
            published_at DATETIME,
            description TEXT,
            transcript_status VARCHAR(20) NOT NULL,
            transcript_language VARCHAR(10),
            transcript_word_count INTEGER,
            transcript_source VARCHAR(20),
            transcripted_at DATETIME,
            embedded_in_chroma BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            extracted_knowledge_json TEXT,
            knowledge_report_md TEXT,
            knowledge_extracted_at DATETIME,
            source_type VARCHAR(20) NOT NULL,
            source_id VARCHAR(255) NOT NULL,
            source_url VARCHAR(500),
            source_metadata_json TEXT,
            language VARCHAR(10),
            word_count INTEGER,
            user_provenance_json TEXT,
            FOREIGN KEY(channel_id) REFERENCES channels(channel_id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO documents_new (
            document_id, video_id, channel_id, title, url, thumbnail_url,
            duration_seconds, published_at, description,
            transcript_status, transcript_language, transcript_word_count,
            transcript_source, transcripted_at, embedded_in_chroma,
            created_at, updated_at,
            extracted_knowledge_json, knowledge_report_md, knowledge_extracted_at,
            source_type, source_id, source_url, source_metadata_json,
            language, word_count, user_provenance_json
        )
        SELECT
            document_id, video_id, channel_id, title, url, thumbnail_url,
            duration_seconds, published_at, description,
            transcript_status, transcript_language, transcript_word_count,
            transcript_source, transcripted_at, embedded_in_chroma,
            created_at, updated_at,
            extracted_knowledge_json, knowledge_report_md, knowledge_extracted_at,
            source_type, source_id, source_url, source_metadata_json,
            language, word_count, user_provenance_json
        FROM documents
        """
    )
    op.execute("DROP TABLE documents")
    op.execute("ALTER TABLE documents_new RENAME TO documents")
    op.create_index("ix_documents_channel_id", "documents", ["channel_id"])
    op.create_index(
        "ix_documents_source_type_source_id",
        "documents",
        ["source_type", "source_id"],
        unique=True,
    )
    op.create_index("ix_documents_video_id", "documents", ["video_id"])


def downgrade() -> None:
    """Best-effort reverse — assumes legacy video_id columns are still
    populated post-cutover so we can restore the original PK shape.
    Production safety relies on a pre-cutover DB file backup, not this
    path. The round-trip test (T-1.10.8) validates downgrade on a
    synthetic post-upgrade DB."""

    # documents: rebuild with video_id PK + document_id non-PK column.
    op.drop_index("ix_documents_video_id", table_name="documents")
    op.drop_index(
        "ix_documents_source_type_source_id", table_name="documents"
    )
    op.drop_index("ix_documents_channel_id", table_name="documents")
    op.execute(
        """
        CREATE TABLE documents_old (
            video_id VARCHAR(20) NOT NULL PRIMARY KEY,
            channel_id VARCHAR(50),
            title VARCHAR(500) NOT NULL,
            url VARCHAR(200) NOT NULL,
            thumbnail_url VARCHAR(500),
            duration_seconds INTEGER,
            published_at DATETIME,
            description TEXT,
            transcript_status VARCHAR(20) NOT NULL,
            transcript_language VARCHAR(10),
            transcript_word_count INTEGER,
            transcript_source VARCHAR(20),
            transcripted_at DATETIME,
            embedded_in_chroma BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            extracted_knowledge_json TEXT,
            knowledge_report_md TEXT,
            knowledge_extracted_at DATETIME,
            source_type VARCHAR(20) NOT NULL,
            source_id VARCHAR(255) NOT NULL,
            source_url VARCHAR(500),
            source_metadata_json TEXT,
            language VARCHAR(10),
            word_count INTEGER,
            user_provenance_json TEXT,
            document_id VARCHAR(36) NOT NULL,
            FOREIGN KEY(channel_id) REFERENCES channels(channel_id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO documents_old SELECT
            video_id, channel_id, title, url, thumbnail_url,
            duration_seconds, published_at, description,
            transcript_status, transcript_language, transcript_word_count,
            transcript_source, transcripted_at, embedded_in_chroma,
            created_at, updated_at,
            extracted_knowledge_json, knowledge_report_md, knowledge_extracted_at,
            source_type, source_id, source_url, source_metadata_json,
            language, word_count, user_provenance_json, document_id
        FROM documents
        WHERE video_id IS NOT NULL
        """
    )
    op.execute("DROP TABLE documents")
    op.execute("ALTER TABLE documents_old RENAME TO documents")
    op.create_index("ix_documents_channel_id", "documents", ["channel_id"])
    op.create_index(
        "ix_documents_source_type_source_id",
        "documents",
        ["source_type", "source_id"],
        unique=True,
    )
    op.create_index(
        "ix_documents_document_id", "documents", ["document_id"], unique=True
    )

    # transcript_cache: rebuild with video_id PK, drop document_id.
    op.execute(
        """
        CREATE TABLE transcript_cache_old (
            video_id VARCHAR(20) NOT NULL PRIMARY KEY,
            segments_json TEXT NOT NULL,
            language VARCHAR(10) NOT NULL,
            fetched_at DATETIME NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO transcript_cache_old (video_id, segments_json, language, fetched_at)
        SELECT video_id, segments_json, language, fetched_at
        FROM transcript_cache
        WHERE video_id IS NOT NULL
        """
    )
    op.execute("DROP TABLE transcript_cache")
    op.execute("ALTER TABLE transcript_cache_old RENAME TO transcript_cache")

    # job_documents → job_videos: rebuild with old PK shape.
    op.drop_index("ix_job_documents_video_id", table_name="job_documents")
    op.drop_index("ix_job_documents_document_id", table_name="job_documents")
    op.drop_index("ix_job_documents_job_id", table_name="job_documents")
    op.execute(
        """
        CREATE TABLE job_videos (
            job_id VARCHAR(36) NOT NULL,
            video_id VARCHAR(20) NOT NULL,
            approved BOOLEAN NOT NULL,
            curated_at DATETIME NOT NULL,
            selection_reason TEXT,
            PRIMARY KEY (job_id, video_id),
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        INSERT INTO job_videos (job_id, video_id, approved, curated_at, selection_reason)
        SELECT job_id, video_id, approved, curated_at, selection_reason
        FROM job_documents
        WHERE video_id IS NOT NULL
        """
    )
    op.execute("DROP TABLE job_documents")
    op.create_index("ix_job_videos_job_id", "job_videos", ["job_id"])
    op.create_index("ix_job_videos_video_id", "job_videos", ["video_id"])
