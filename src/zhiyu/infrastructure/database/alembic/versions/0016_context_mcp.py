"""Add derived conversation summaries and MCP tool allowlists."""

from alembic import op
import sqlalchemy as sa


revision = "0016_context_mcp"
down_revision = "0015_channel_reliability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_summaries",
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_message_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("mcp_server_configs") as batch:
        batch.add_column(
            sa.Column(
                "tool_allowlist_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("mcp_server_configs") as batch:
        batch.drop_column("tool_allowlist_json")
    op.drop_table("conversation_summaries")
