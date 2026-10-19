"""tags + taggings — per-tenant labels on documents (S-8.1.3 / E-8.1)

Revision ID: e9f0a1b2c3d4
Revises: a9f3c1e7b5d2
Create Date: 2026-10-19

Two additive tables, no data migration. `tags` is unique per tenant on
`lower(name)` (a functional index; SQLite supports it). `taggings` is
polymorphic on `(target_type, target_id)` with one row per tag per target,
and carries `tenant_id` so reads filter without a join. Downgrade drops both;
documents are never touched.
"""
import sqlalchemy as sa
from alembic import op

revision = "e9f0a1b2c3d4"
down_revision = "a9f3c1e7b5d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("color", sa.String(20), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tags_tenant_id", "tags", ["tenant_id"])
    op.create_index(
        "uq_tags_tenant_lower_name",
        "tags",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "taggings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tag_id",
            sa.String(36),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tag_id", "target_type", "target_id", name="uq_taggings_tag_target"),
    )
    op.create_index("ix_taggings_tag_id", "taggings", ["tag_id"])
    op.create_index(
        "ix_taggings_tenant_target", "taggings", ["tenant_id", "target_type", "target_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_taggings_tenant_target", table_name="taggings")
    op.drop_index("ix_taggings_tag_id", table_name="taggings")
    op.drop_table("taggings")
    op.drop_index("uq_tags_tenant_lower_name", table_name="tags")
    op.drop_index("ix_tags_tenant_id", table_name="tags")
    op.drop_table("tags")
