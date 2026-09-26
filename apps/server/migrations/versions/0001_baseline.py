"""Baseline the MVP database schema without replacing existing tables."""

from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "conversations" not in existing:
        op.create_table(
            "conversations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("character_id", sa.String(36), nullable=True),
            sa.Column("channel", sa.String(32), nullable=False),
            sa.Column("external_user_id", sa.String(255), nullable=True),
            sa.Column("model_id", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if "messages" not in existing:
        op.create_table(
            "messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    if "providers" not in existing:
        op.create_table(
            "providers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("provider_type", sa.String(32), nullable=False),
            sa.Column("api_key_ref", sa.String(255), nullable=True),
            sa.Column("base_url", sa.String(255), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False),
        )
    if "model_configs" not in existing:
        op.create_table(
            "model_configs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("provider_id", sa.String(36), sa.ForeignKey("providers.id"), nullable=False),
            sa.Column("model_name", sa.String(255), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("supports_tools", sa.Boolean(), nullable=False),
            sa.Column("supports_streaming", sa.Boolean(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
        )
        op.create_index("ix_model_configs_provider_id", "model_configs", ["provider_id"])
    if "characters" not in existing:
        op.create_table(
            "characters",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("avatar", sa.String(255), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("personality", sa.Text(), nullable=True),
            sa.Column("background", sa.Text(), nullable=True),
            sa.Column("speaking_style", sa.Text(), nullable=True),
            sa.Column("system_prompt", sa.Text(), nullable=True),
            sa.Column("default_model_id", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if "memories" not in existing:
        op.create_table(
            "memories",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("type", sa.String(32), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("importance", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    for table in ("memories", "characters", "model_configs", "providers", "messages", "conversations"):
        op.drop_table(table)
