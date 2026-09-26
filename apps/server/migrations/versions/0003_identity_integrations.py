"""Add identities, isolated memories and persistent integration configs."""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0003_identity_integrations"
down_revision = "0002_phase12"
branch_labels = None
depends_on = None

LOCAL_IDENTITY_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("channel", "external_user_id", name="uq_identity_channel_user"),
    )
    op.execute(
        "INSERT INTO identities (id, channel, external_user_id, display_name, created_at, updated_at) "
        f"VALUES ('{LOCAL_IDENTITY_ID}', 'desktop', 'local-user', 'Local User', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("identity_id", sa.String(36), nullable=True))
    with op.batch_alter_table("memories") as batch:
        batch.add_column(sa.Column("identity_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.execute(
        f"UPDATE conversations SET identity_id = '{LOCAL_IDENTITY_ID}' "
        "WHERE channel = 'desktop' AND identity_id IS NULL"
    )
    op.execute(
        f"UPDATE memories SET identity_id = '{LOCAL_IDENTITY_ID}' WHERE identity_id IS NULL"
    )

    connection = op.get_bind()
    qq_users = connection.execute(
        sa.text(
            "SELECT DISTINCT external_user_id FROM conversations "
            "WHERE channel = 'qq' AND external_user_id IS NOT NULL"
        )
    ).scalars()
    for external_user_id in qq_users:
        identity_id = str(uuid4())
        connection.execute(
            sa.text(
                "INSERT INTO identities "
                "(id, channel, external_user_id, created_at, updated_at) "
                "VALUES (:id, 'qq', :external_user_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": identity_id, "external_user_id": external_user_id},
        )
        connection.execute(
            sa.text(
                "UPDATE conversations SET identity_id = :identity_id "
                "WHERE channel = 'qq' AND external_user_id = :external_user_id"
            ),
            {"identity_id": identity_id, "external_user_id": external_user_id},
        )

    op.create_index("ix_conversations_identity_id", "conversations", ["identity_id"])
    op.create_index("ix_memories_identity_id", "memories", ["identity_id"])

    op.create_table(
        "channel_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("endpoint", sa.String(500), nullable=False),
        sa.Column("secret_ref", sa.String(255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_connect", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "mcp_server_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("command", sa.String(500), nullable=False),
        sa.Column("args_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_connect", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mcp_server_configs")
    op.drop_table("channel_configs")
    with op.batch_alter_table("memories") as batch:
        batch.drop_index("ix_memories_identity_id")
        batch.drop_column("shared")
        batch.drop_column("identity_id")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_index("ix_conversations_identity_id")
        batch.drop_column("identity_id")
    op.drop_table("identities")
