"""visual frames + per-job visual opt-in (R1 / S-1.18.1)

Revision ID: a7b8c9d1e2f3
Revises: f6a7b8c9d1e2
Create Date: 2026-07-31

Adds the `visual_frames` table (captured stills + their descriptions, keyed
on the document so they are computed once and reused) and `jobs.visual_analysis`,
the per-job opt-in. Both halves of the gate must be true for any frame work to
happen: the install-wide `VISUAL_ENABLED` setting AND this column.

Purely additive. Existing jobs default to opt-out, which is the safe read of
"the user never asked for this".
"""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d1e2f3"
down_revision = "f6a7b8c9d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visual_frames",
        sa.Column("frame_id", sa.String(36), primary_key=True),
        sa.Column(
            "video_id",
            sa.String(64),
            sa.ForeignKey("documents.video_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("timestamp_seconds", sa.Float(), nullable=False),
        sa.Column("image_path", sa.String(500), nullable=True),
        sa.Column("selection_reason", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("informative", sa.Boolean(), nullable=True),
        sa.Column("description_model", sa.String(100), nullable=True),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="captured"
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("described_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "video_id", "timestamp_seconds", name="uq_visual_frame_ts"
        ),
    )
    op.create_index("ix_visual_frames_video_id", "visual_frames", ["video_id"])
    op.create_index(
        "ix_visual_frames_video_status", "visual_frames", ["video_id", "status"]
    )

    with op.batch_alter_table("jobs") as batch:
        batch.add_column(
            sa.Column(
                "visual_analysis",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("visual_analysis")
    op.drop_index("ix_visual_frames_video_status", table_name="visual_frames")
    op.drop_index("ix_visual_frames_video_id", table_name="visual_frames")
    op.drop_table("visual_frames")
