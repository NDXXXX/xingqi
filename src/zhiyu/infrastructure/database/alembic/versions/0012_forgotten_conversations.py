"""Add forgotten-conversation tombstones."""

from alembic import op
import sqlalchemy as sa

revision = "0012_forgotten_conversations"
down_revision = "0011_memory_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forgotten_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_forgotten_conversations_conversation_id",
        "forgotten_conversations",
        ["conversation_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("forgotten_conversations")
