"""document_visibility — per-tenant grants over the shared document cache

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b9
Create Date: 2026-07-31

S-5.7.1 / D-063. Includes a BACKFILL: every existing document gains a grant
for each tenant whose jobs selected it, so nobody loses access at deploy.
Documents belonging to no job (PDF uploads, pasted URLs, channel syncs from
before this change) cannot be attributed to a tenant retroactively and are
left ungranted — they become invisible, which is the safe direction. That is
called out in the ADR so the operator can re-grant deliberately.
"""
import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c0"
down_revision = "c3d4e5f6a7b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_visibility",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "video_id",
            sa.String(64),
            sa.ForeignKey("documents.video_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(24), nullable=False, server_default="job"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("video_id", "tenant_id", name="uq_document_visibility"),
    )
    op.create_index("ix_document_visibility_video_id", "document_visibility", ["video_id"])
    op.create_index("ix_document_visibility_tenant_id", "document_visibility", ["tenant_id"])
    op.create_index(
        "ix_document_visibility_tenant_video", "document_visibility", ["tenant_id", "video_id"]
    )

    # Backfill from job ownership. lower(hex(randomblob(16))) gives SQLite a
    # unique id without needing uuid in SQL; other backends get a row per pair
    # from the same SELECT DISTINCT.
    op.execute(
        """
        INSERT INTO document_visibility (id, video_id, tenant_id, source, created_at)
        SELECT lower(hex(randomblob(16))), jd.video_id, j.tenant_id, 'job', CURRENT_TIMESTAMP
        FROM (SELECT DISTINCT video_id, job_id FROM job_documents) jd
        JOIN jobs j ON j.id = jd.job_id
        WHERE j.tenant_id IS NOT NULL
        GROUP BY jd.video_id, j.tenant_id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_document_visibility_tenant_video", table_name="document_visibility")
    op.drop_index("ix_document_visibility_tenant_id", table_name="document_visibility")
    op.drop_index("ix_document_visibility_video_id", table_name="document_visibility")
    op.drop_table("document_visibility")
