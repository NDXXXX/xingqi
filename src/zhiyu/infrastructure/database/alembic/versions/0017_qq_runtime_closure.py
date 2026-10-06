"""Add recoverable QQ events, structured messages, media and group policies."""

from alembic import op
import sqlalchemy as sa


revision = "0017_qq_runtime_closure"
down_revision = "0016_context_mcp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table(
        "channel_configs",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch:
        batch.drop_constraint("uq_channel_configs_channel", type_="unique")
        batch.add_column(
            sa.Column(
                "account_id",
                sa.String(255),
                nullable=False,
                server_default="qq-onebot-default",
            )
        )
        batch.add_column(
            sa.Column(
                "driver",
                sa.String(64),
                nullable=False,
                server_default="onebot_reverse_ws",
            )
        )
        batch.create_unique_constraint(
            "uq_channel_config_account", ["channel", "account_id"]
        )

    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("channel_config_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("external_conversation_type", sa.String(32), nullable=True))
        batch.create_foreign_key(
            "fk_conversations_channel_config",
            "channel_configs",
            ["channel_config_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_conversations_channel_config_id", ["channel_config_id"])

    op.execute(
        "UPDATE conversations SET channel_config_id = "
        "(SELECT id FROM channel_configs WHERE channel = conversations.channel LIMIT 1) "
        "WHERE channel != 'local' AND channel_config_id IS NULL"
    )

    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("parts_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_event_id", sa.String(255), nullable=True))
        batch.create_index("ix_messages_source_event_id", ["source_event_id"])

    with op.batch_alter_table("model_configs") as batch:
        batch.add_column(
            sa.Column(
                "supports_vision", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )

    with op.batch_alter_table("channel_events") as batch:
        batch.add_column(sa.Column("channel_config_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column("available_at", sa.DateTime(), nullable=True)
        )
        batch.add_column(sa.Column("lease_owner", sa.String(255), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("response_message_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("outbound_message_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key(
            "fk_channel_events_channel_config",
            "channel_configs",
            ["channel_config_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_channel_events_response_message",
            "messages",
            ["response_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_channel_events_channel_config_id", ["channel_config_id"])

    op.execute(
        "UPDATE channel_events SET channel_config_id = "
        "(SELECT id FROM channel_configs WHERE channel = channel_events.channel "
        "AND account_id = channel_events.account_id LIMIT 1)"
    )
    op.execute(
        "UPDATE channel_events SET available_at = received_at, updated_at = received_at"
    )
    op.execute(
        "UPDATE channel_events SET status = 'pending', attempts = 0 "
        "WHERE status = 'processing'"
    )
    with op.batch_alter_table("channel_events") as batch:
        batch.alter_column("available_at", nullable=False)
        batch.alter_column("updated_at", nullable=False)

    with op.batch_alter_table("channel_deliveries") as batch:
        batch.add_column(sa.Column("channel_config_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("retry_of_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("message_json", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_channel_deliveries_channel_config",
            "channel_configs",
            ["channel_config_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_channel_deliveries_retry_of",
            "channel_deliveries",
            ["retry_of_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_channel_deliveries_channel_config_id", ["channel_config_id"])

    op.execute(
        "UPDATE channel_deliveries SET channel_config_id = "
        "(SELECT channel_config_id FROM channel_events "
        "WHERE channel_events.id = channel_deliveries.event_id)"
    )

    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("channel_event_id", sa.String(255), nullable=True))
        batch.add_column(sa.Column("response_message_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_agent_runs_channel_event",
            "channel_events",
            ["channel_event_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_agent_runs_response_message",
            "messages",
            ["response_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint("uq_agent_runs_channel_event", ["channel_event_id"])

    op.create_table(
        "channel_group_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "channel_config_id",
            sa.String(36),
            sa.ForeignKey("channel_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_group_id", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("require_mention", sa.Boolean(), nullable=False),
        sa.Column("tool_allowlist_json", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "channel_config_id", "external_group_id", name="uq_channel_group_policy"
        ),
    )
    op.create_index(
        "ix_channel_group_policies_channel_config_id",
        "channel_group_policies",
        ["channel_config_id"],
    )

    op.create_table(
        "channel_media_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "channel_config_id",
            sa.String(36),
            sa.ForeignKey("channel_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_event_id", sa.String(255), nullable=True),
        sa.Column("relative_path", sa.String(1000), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_channel_media_assets_channel_config_id",
        "channel_media_assets",
        ["channel_config_id"],
    )
    op.create_index(
        "ix_channel_media_assets_source_event_id",
        "channel_media_assets",
        ["source_event_id"],
    )
    op.create_index(
        "ix_channel_media_assets_sha256", "channel_media_assets", ["sha256"]
    )


def downgrade() -> None:
    op.drop_table("channel_media_assets")
    op.drop_table("channel_group_policies")

    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("uq_agent_runs_channel_event", type_="unique")
        batch.drop_constraint("fk_agent_runs_response_message", type_="foreignkey")
        batch.drop_constraint("fk_agent_runs_channel_event", type_="foreignkey")
        batch.drop_column("response_message_id")
        batch.drop_column("channel_event_id")

    with op.batch_alter_table("channel_deliveries") as batch:
        batch.drop_index("ix_channel_deliveries_channel_config_id")
        batch.drop_constraint("fk_channel_deliveries_retry_of", type_="foreignkey")
        batch.drop_constraint("fk_channel_deliveries_channel_config", type_="foreignkey")
        batch.drop_column("message_json")
        batch.drop_column("retry_of_id")
        batch.drop_column("channel_config_id")

    with op.batch_alter_table("channel_events") as batch:
        batch.drop_index("ix_channel_events_channel_config_id")
        batch.drop_constraint("fk_channel_events_response_message", type_="foreignkey")
        batch.drop_constraint("fk_channel_events_channel_config", type_="foreignkey")
        batch.drop_column("updated_at")
        batch.drop_column("outbound_message_json")
        batch.drop_column("response_message_id")
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_owner")
        batch.drop_column("available_at")
        batch.drop_column("channel_config_id")

    with op.batch_alter_table("model_configs") as batch:
        batch.drop_column("supports_vision")

    with op.batch_alter_table("messages") as batch:
        batch.drop_index("ix_messages_source_event_id")
        batch.drop_column("source_event_id")
        batch.drop_column("parts_json")

    with op.batch_alter_table("conversations") as batch:
        batch.drop_index("ix_conversations_channel_config_id")
        batch.drop_constraint("fk_conversations_channel_config", type_="foreignkey")
        batch.drop_column("external_conversation_type")
        batch.drop_column("channel_config_id")

    with op.batch_alter_table("channel_configs") as batch:
        batch.drop_constraint("uq_channel_config_account", type_="unique")
        batch.drop_column("driver")
        batch.drop_column("account_id")
        batch.create_unique_constraint("uq_channel_configs_channel", ["channel"])
