"""Add memory provenance and lifecycle fields."""

from alembic import op
import sqlalchemy as sa

revision = "0007_memory_lifecycle"
down_revision = "0006_local_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.add_column(sa.Column("status", sa.String(32), nullable=True))
        batch.add_column(sa.Column("source_message_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("status_source_message_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("supersedes_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("origin", sa.String(32), nullable=True))

    op.execute("UPDATE memories SET status = 'active' WHERE status IS NULL")
    op.execute("UPDATE memories SET origin = 'legacy' WHERE origin IS NULL")

    with op.batch_alter_table("memories") as batch:
        batch.alter_column("status", nullable=False)
        batch.alter_column("origin", nullable=False)
        batch.create_foreign_key(
            "fk_memories_source_message", "messages", ["source_message_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_memories_status_source_message",
            "messages",
            ["status_source_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_memories_supersedes", "memories", ["supersedes_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_memories_identity_status", ["identity_id", "status"])


def downgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.drop_index("ix_memories_identity_status")
        batch.drop_constraint("fk_memories_supersedes", type_="foreignkey")
        batch.drop_constraint("fk_memories_status_source_message", type_="foreignkey")
        batch.drop_constraint("fk_memories_source_message", type_="foreignkey")
        batch.drop_column("origin")
        batch.drop_column("supersedes_id")
        batch.drop_column("status_source_message_id")
        batch.drop_column("source_message_id")
        batch.drop_column("status")
