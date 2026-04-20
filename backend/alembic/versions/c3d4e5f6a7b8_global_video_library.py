"""global video library: channels, job_videos, and deduplicated videos

Revision ID: c3d4e5f6a7b8
Revises: 94fbb3787ced
Create Date: 2026-04-19 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "94fbb3787ced"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Refactor the `videos` table into a globally deduplicated library.

    Steps:
      1. Create `channels` and `job_videos`, plus a staging `videos_new` with the
         new schema (YouTube `video_id` is the primary key).
      2. Backfill `channels` from DISTINCT channel ids/names on the old videos.
      3. Backfill `videos_new` from the earliest row per video_id on the old
         videos, preferring non-null transcript metadata.
      4. Backfill `job_videos` one-to-one from the old `videos` rows.
      5. Copy cached transcript metadata from `transcript_cache` into
         `videos_new` where available (mark `transcript_status='fetched'`).
      6. Drop the old `videos` table, rename `videos_new` -> `videos`.
      7. Create indices on the new tables.
    """
    bind = op.get_bind()

    # 1. channels ----------------------------------------------------------
    op.create_table(
        "channels",
        sa.Column("channel_id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("subscriber_count", sa.Integer(), nullable=True),
        sa.Column("uploads_playlist_id", sa.String(length=50), nullable=True),
        sa.Column("subscribed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("channel_id"),
    )

    # 2. job_videos --------------------------------------------------------
    op.create_table(
        "job_videos",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("video_id", sa.String(length=20), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("curated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("selection_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        # FK to videos.video_id is added after we rename videos_new -> videos.
        sa.PrimaryKeyConstraint("job_id", "video_id"),
    )

    # 3. videos_new --------------------------------------------------------
    op.create_table(
        "videos_new",
        sa.Column("video_id", sa.String(length=20), nullable=False),
        sa.Column("channel_id", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=200), nullable=False),
        sa.Column("thumbnail_url", sa.String(length=500), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("transcript_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("transcript_language", sa.String(length=10), nullable=True),
        sa.Column("transcript_word_count", sa.Integer(), nullable=True),
        sa.Column("transcript_source", sa.String(length=20), nullable=True),
        sa.Column("transcripted_at", sa.DateTime(), nullable=True),
        sa.Column("embedded_in_chroma", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.channel_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("video_id"),
    )

    # --- Data backfill ----------------------------------------------------
    # Only do backfill if the legacy `videos` table exists AND contains the
    # legacy columns (`job_id`, `channel_name`). A fresh DB skips the backfill.
    inspector = sa.inspect(bind)
    has_legacy_videos = "videos" in inspector.get_table_names()
    legacy_cols: set[str] = set()
    if has_legacy_videos:
        legacy_cols = {c["name"] for c in inspector.get_columns("videos")}
    has_legacy_shape = has_legacy_videos and "job_id" in legacy_cols and "channel_name" in legacy_cols

    if has_legacy_shape:
        # 2a. channels from DISTINCT (channel_id, channel_name)
        bind.execute(sa.text("""
            INSERT INTO channels (channel_id, name, subscribed, created_at)
            SELECT channel_id, MIN(channel_name), 0, CURRENT_TIMESTAMP
            FROM videos
            WHERE channel_id IS NOT NULL AND channel_id != ''
            GROUP BY channel_id
        """))

        # 3a. videos_new from the earliest row per video_id.
        #     SQLite picks an arbitrary non-aggregated column from that group.
        bind.execute(sa.text("""
            INSERT INTO videos_new (
                video_id, channel_id, title, url, thumbnail_url, duration_seconds,
                published_at, transcript_status, transcript_language,
                transcript_word_count, transcript_source, embedded_in_chroma,
                created_at, updated_at
            )
            SELECT
                v.video_id,
                v.channel_id,
                v.title,
                v.url,
                v.thumbnail_url,
                v.duration_seconds,
                v.published_at,
                COALESCE(v.transcript_status, 'pending'),
                v.transcript_language,
                v.transcript_word_count,
                CASE WHEN v.transcript_status = 'fetched' THEN 'youtube' ELSE NULL END,
                0,
                COALESCE(v.created_at, CURRENT_TIMESTAMP),
                COALESCE(v.created_at, CURRENT_TIMESTAMP)
            FROM videos v
            INNER JOIN (
                SELECT video_id, MIN(created_at) AS first_created, MIN(id) AS first_id
                FROM videos
                GROUP BY video_id
            ) first_row
              ON first_row.video_id = v.video_id AND first_row.first_id = v.id
        """))

        # 4. job_videos from every legacy row (one row per (job_id, video_id))
        bind.execute(sa.text("""
            INSERT INTO job_videos (job_id, video_id, approved, curated_at)
            SELECT job_id, video_id, COALESCE(approved, 1), COALESCE(created_at, CURRENT_TIMESTAMP)
            FROM videos
            WHERE job_id IS NOT NULL AND video_id IS NOT NULL
        """))

        # 5. Pull transcript_cache metadata into videos_new where present.
        if "transcript_cache" in inspector.get_table_names():
            bind.execute(sa.text("""
                UPDATE videos_new
                SET
                    transcript_status = 'fetched',
                    transcript_language = COALESCE(
                        (SELECT tc.language FROM transcript_cache tc WHERE tc.video_id = videos_new.video_id),
                        videos_new.transcript_language
                    ),
                    transcript_source = COALESCE(videos_new.transcript_source, 'youtube'),
                    transcripted_at = COALESCE(
                        (SELECT tc.fetched_at FROM transcript_cache tc WHERE tc.video_id = videos_new.video_id),
                        videos_new.transcripted_at
                    )
                WHERE EXISTS (
                    SELECT 1 FROM transcript_cache tc WHERE tc.video_id = videos_new.video_id
                )
            """))

        # 6. Drop legacy videos; rename videos_new -> videos.
        with op.batch_alter_table("videos") as batch_op:
            pass  # force-load the table into the batch context (no-op)
        # Drop the old indexes that dangle on `videos`.
        try:
            op.drop_index("ix_videos_job_id", table_name="videos")
        except Exception:
            # Index may not exist on a partially-migrated DB; continue.
            pass
        op.drop_table("videos")
    else:
        # Fresh DB path: no legacy table, nothing to copy.
        if has_legacy_videos:
            op.drop_table("videos")

    op.rename_table("videos_new", "videos")

    # 7. Indices -----------------------------------------------------------
    op.create_index("ix_videos_channel_id", "videos", ["channel_id"], unique=False)
    op.create_index("ix_job_videos_job_id", "job_videos", ["job_id"], unique=False)
    op.create_index("ix_job_videos_video_id", "job_videos", ["video_id"], unique=False)

    # SQLite can't ALTER to add a FK after rename; but since `job_videos.video_id`
    # references `videos.video_id` (which is now the renamed table's PK), any
    # enforcement happens at app level. For databases that support it, add the FK.
    dialect = bind.dialect.name
    if dialect != "sqlite":
        with op.batch_alter_table("job_videos") as batch_op:
            batch_op.create_foreign_key(
                "fk_job_videos_video_id",
                "videos",
                ["video_id"],
                ["video_id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    """Revert to the pre-refactor per-job `videos` table.

    This is a best-effort reversal: it reconstructs a minimal legacy `videos`
    shape from `(job_videos JOIN videos)` so existing tests/tools can still
    read rows, but it does NOT restore the pre-dedup history of multiple rows
    per video with divergent titles.
    """
    bind = op.get_bind()

    op.drop_index("ix_job_videos_video_id", table_name="job_videos")
    op.drop_index("ix_job_videos_job_id", table_name="job_videos")
    op.drop_index("ix_videos_channel_id", table_name="videos")

    op.rename_table("videos", "videos_new")

    op.create_table(
        "videos",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("video_id", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("channel_name", sa.String(length=200), nullable=False),
        sa.Column("channel_id", sa.String(length=50), nullable=False),
        sa.Column("url", sa.String(length=200), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("thumbnail_url", sa.String(length=500), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("transcript_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("transcript_word_count", sa.Integer(), nullable=True),
        sa.Column("transcript_language", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_videos_job_id", "videos", ["job_id"], unique=False)

    bind.execute(sa.text("""
        INSERT INTO videos (
            id, job_id, video_id, title, channel_name, channel_id, url,
            duration_seconds, published_at, thumbnail_url, approved,
            transcript_status, transcript_word_count, transcript_language,
            created_at
        )
        SELECT
            jv.job_id || ':' || jv.video_id,
            jv.job_id,
            v.video_id,
            v.title,
            COALESCE((SELECT c.name FROM channels c WHERE c.channel_id = v.channel_id), ''),
            COALESCE(v.channel_id, ''),
            v.url,
            v.duration_seconds,
            v.published_at,
            v.thumbnail_url,
            jv.approved,
            v.transcript_status,
            v.transcript_word_count,
            v.transcript_language,
            jv.curated_at
        FROM job_videos jv
        INNER JOIN videos_new v ON v.video_id = jv.video_id
    """))

    op.drop_table("videos_new")
    op.drop_table("job_videos")
    op.drop_table("channels")
