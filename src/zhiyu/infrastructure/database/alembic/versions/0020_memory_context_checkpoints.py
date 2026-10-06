"""Add incremental memory file indexes and context checkpoint boundaries."""

from alembic import op
import sqlalchemy as sa


revision = "0020_memory_context_checkpoints"
down_revision = "0019_installed_skill_trash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("last_evidence_at", sa.DateTime(), nullable=True),
    )
    op.execute("UPDATE memories SET last_evidence_at = observed_at WHERE last_evidence_at IS NULL")
    op.add_column(
        "conversation_summaries",
        sa.Column("last_message_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "conversation_summaries",
        sa.Column("last_message_created_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "memory_consolidation_runs",
        sa.Column("details_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "memory_file_indexes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "identity_id",
            sa.String(length=36),
            sa.ForeignKey("identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mtime_ns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("indexed_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "identity_id", "file_path", name="uq_memory_file_index_identity_path"
        ),
    )
    op.create_index(
        "ix_memory_file_indexes_identity_id",
        "memory_file_indexes",
        ["identity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_file_indexes_identity_id", table_name="memory_file_indexes")
    op.drop_table("memory_file_indexes")
    op.drop_column("conversation_summaries", "last_message_created_at")
    op.drop_column("conversation_summaries", "last_message_id")
    op.drop_column("memory_consolidation_runs", "details_json")
    op.drop_column("memories", "last_evidence_at")
