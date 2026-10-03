"""Add memory embedding vector store."""

from alembic import op
import sqlalchemy as sa

revision = "0011_memory_embeddings"
down_revision = "0010_memory_consolidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_embeddings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "memory_id",
            sa.String(36),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("vector_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("memory_id", "model", name="uq_memory_embedding_model"),
    )
    op.create_index("ix_memory_embeddings_memory_id", "memory_embeddings", ["memory_id"])


def downgrade() -> None:
    op.drop_table("memory_embeddings")
