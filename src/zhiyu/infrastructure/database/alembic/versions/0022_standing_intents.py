"""Persist scoped standing reminders."""

import sqlalchemy as sa
from alembic import op


revision = "0022_standing_intents"
down_revision = "0021_memory_fts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "standing_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("identity_id", sa.String(36), sa.ForeignKey("identities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("source_conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("topic", sa.String(100), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("channel_config_id", sa.String(36), nullable=True),
        sa.Column("target_id", sa.String(255), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
        sa.Column("fire_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_standing_intents_identity_id", "standing_intents", ["identity_id"])
    op.create_index("ix_standing_intents_due", "standing_intents", ["status", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_standing_intents_due", table_name="standing_intents")
    op.drop_index("ix_standing_intents_identity_id", table_name="standing_intents")
    op.drop_table("standing_intents")
