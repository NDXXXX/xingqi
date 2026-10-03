"""Add identity-scoped memory lineage, stable entries, recall events, and mutations."""

from alembic import op
import sqlalchemy as sa


revision = "0013_memory_vaults"
down_revision = "0012_forgotten_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.add_column(sa.Column("entry_key", sa.String(64), nullable=True))
        batch.create_index("ix_memories_entry_key", ["entry_key"])

    # The old table had a global unique conversation id and no identity boundary.
    # Existing rows were created only by the local-only CLI, so preserve them under
    # the stable local identity rather than silently discarding tombstones.
    op.drop_index(
        "ix_forgotten_conversations_conversation_id",
        table_name="forgotten_conversations",
    )
    op.rename_table("forgotten_conversations", "forgotten_conversations_legacy")
    op.create_table(
        "forgotten_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "identity_id",
            sa.String(36),
            sa.ForeignKey("identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "identity_id", "conversation_id", name="uq_forgotten_conversation_identity"
        ),
    )
    op.create_index(
        "ix_forgotten_conversations_identity_id",
        "forgotten_conversations",
        ["identity_id"],
    )
    op.create_index(
        "ix_forgotten_conversations_conversation_id",
        "forgotten_conversations",
        ["conversation_id"],
    )
    op.execute(
        "INSERT INTO forgotten_conversations "
        "(id, identity_id, conversation_id, created_at) "
        "SELECT id, '00000000-0000-0000-0000-000000000001', "
        "conversation_id, created_at FROM forgotten_conversations_legacy"
    )
    op.drop_table("forgotten_conversations_legacy")

    op.create_table(
        "memory_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "memory_id",
            sa.String(36),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            sa.String(36),
            sa.ForeignKey("identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_memory_id",
            sa.String(36),
            sa.ForeignKey("memories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("trust", sa.String(16), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "memory_id",
            "source_memory_id",
            "source_message_id",
            name="uq_memory_source_lineage",
        ),
    )
    op.create_index("ix_memory_sources_memory_id", "memory_sources", ["memory_id"])
    op.create_index("ix_memory_sources_identity_id", "memory_sources", ["identity_id"])
    op.create_index(
        "ix_memory_sources_conversation_id", "memory_sources", ["conversation_id"]
    )

    op.create_table(
        "memory_recall_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "memory_id",
            sa.String(36),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            sa.String(36),
            sa.ForeignKey("identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("recall_mode", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_memory_recall_events_memory_id", "memory_recall_events", ["memory_id"])
    op.create_index("ix_memory_recall_events_identity_id", "memory_recall_events", ["identity_id"])
    op.create_index(
        "ix_memory_recall_identity_created",
        "memory_recall_events",
        ["identity_id", "created_at"],
    )

    op.create_table(
        "memory_mutations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "identity_id",
            sa.String(36),
            sa.ForeignKey("identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("entry_key", sa.String(64), nullable=False),
        sa.Column("expected_file_hash", sa.String(64), nullable=True),
        sa.Column("new_entry_text", sa.Text(), nullable=True),
        sa.Column("new_entry_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_memory_mutations_identity_id", "memory_mutations", ["identity_id"])
    op.create_index(
        "ix_memory_mutation_status_created",
        "memory_mutations",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("memory_mutations")
    op.drop_table("memory_recall_events")
    op.drop_table("memory_sources")

    op.drop_index(
        "ix_forgotten_conversations_conversation_id",
        table_name="forgotten_conversations",
    )
    op.drop_index(
        "ix_forgotten_conversations_identity_id",
        table_name="forgotten_conversations",
    )
    op.rename_table("forgotten_conversations", "forgotten_conversations_vault")
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
    op.execute(
        "INSERT INTO forgotten_conversations (id, conversation_id, created_at) "
        "SELECT MIN(id), conversation_id, MIN(created_at) "
        "FROM forgotten_conversations_vault GROUP BY conversation_id"
    )
    op.drop_table("forgotten_conversations_vault")

    with op.batch_alter_table("memories") as batch:
        batch.drop_index("ix_memories_entry_key")
        batch.drop_column("entry_key")
