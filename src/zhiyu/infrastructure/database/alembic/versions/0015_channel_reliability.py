"""Add durable channel events, delivery receipts, and QQ group policy."""

from alembic import op
import sqlalchemy as sa


revision = "0015_channel_reliability"
down_revision = "0014_qq_owner_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("channel_configs") as batch:
        batch.add_column(
            sa.Column(
                "allow_group_messages",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "group_require_mention",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )

    op.create_table(
        "channel_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(255), nullable=False),
        sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column("conversation_key", sa.String(1000), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "channel",
            "account_id",
            "external_event_id",
            name="uq_channel_event_external",
        ),
    )
    op.create_index(
        "ix_channel_events_status_received",
        "channel_events",
        ["status", "received_at"],
    )

    op.create_table(
        "channel_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(255),
            sa.ForeignKey("channel_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(255), nullable=False, unique=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_channel_deliveries_event_created",
        "channel_deliveries",
        ["event_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("channel_deliveries")
    op.drop_table("channel_events")
    with op.batch_alter_table("channel_configs") as batch:
        batch.drop_column("group_require_mention")
        batch.drop_column("allow_group_messages")
