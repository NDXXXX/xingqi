"""Add memory tiers, trust/source provenance, and file location columns."""

from alembic import op
import sqlalchemy as sa

revision = "0009_memory_tiers"
down_revision = "0008_memory_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.add_column(sa.Column("tier", sa.String(16), nullable=True))
        batch.add_column(sa.Column("trust", sa.String(16), nullable=True))
        batch.add_column(sa.Column("source_kind", sa.String(16), nullable=True))
        batch.add_column(sa.Column("observed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("supersession_key", sa.String(255), nullable=True))
        batch.add_column(sa.Column("trigger_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("promotion_status", sa.String(16), nullable=True))
        batch.add_column(sa.Column("promoted_to_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("conversation_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("file_path", sa.String(255), nullable=True))
        batch.add_column(sa.Column("line_start", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("line_end", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("content_hash", sa.String(64), nullable=True))

    op.execute("UPDATE memories SET tier = 'core' WHERE tier IS NULL")
    op.execute("UPDATE memories SET trust = 'owner' WHERE origin = 'manual' AND trust IS NULL")
    op.execute("UPDATE memories SET trust = 'agent' WHERE trust IS NULL")
    op.execute(
        "UPDATE memories SET source_kind = 'manual' WHERE origin = 'manual' AND source_kind IS NULL"
    )
    op.execute(
        "UPDATE memories SET source_kind = 'message' "
        "WHERE source_kind IS NULL AND source_message_id IS NOT NULL"
    )
    op.execute("UPDATE memories SET source_kind = 'import' WHERE source_kind IS NULL")
    op.execute("UPDATE memories SET observed_at = created_at WHERE observed_at IS NULL")
    op.execute("UPDATE memories SET promotion_status = 'none' WHERE promotion_status IS NULL")

    with op.batch_alter_table("memories") as batch:
        batch.alter_column("tier", nullable=False)
        batch.alter_column("trust", nullable=False)
        batch.alter_column("source_kind", nullable=False)
        batch.alter_column("observed_at", nullable=False)
        batch.alter_column("promotion_status", nullable=False)
        batch.create_foreign_key(
            "fk_memories_promoted_to", "memories", ["promoted_to_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_memories_conversation", "conversations", ["conversation_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_memories_identity_tier_status", ["identity_id", "tier", "status"])


def downgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.drop_index("ix_memories_identity_tier_status")
        batch.drop_constraint("fk_memories_conversation", type_="foreignkey")
        batch.drop_constraint("fk_memories_promoted_to", type_="foreignkey")
        batch.drop_column("content_hash")
        batch.drop_column("line_end")
        batch.drop_column("line_start")
        batch.drop_column("file_path")
        batch.drop_column("conversation_id")
        batch.drop_column("promoted_to_id")
        batch.drop_column("promotion_status")
        batch.drop_column("trigger_text")
        batch.drop_column("supersession_key")
        batch.drop_column("observed_at")
        batch.drop_column("source_kind")
        batch.drop_column("trust")
        batch.drop_column("tier")
