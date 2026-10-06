"""Add MCP transports, runtime state and managed Skills metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0018_mcp_skills_lifecycle"
down_revision = "0017_qq_runtime_closure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("mcp_server_configs") as batch:
        batch.add_column(
            sa.Column("transport", sa.String(32), nullable=False, server_default="stdio")
        )
        batch.alter_column("command", existing_type=sa.String(500), nullable=True)
        batch.add_column(sa.Column("url", sa.String(2000), nullable=True))
        batch.add_column(
            sa.Column("env_json", sa.Text(), nullable=False, server_default="{}")
        )
        batch.add_column(
            sa.Column("secret_refs_json", sa.Text(), nullable=False, server_default="{}")
        )
        batch.add_column(
            sa.Column(
                "legacy_all_tools", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(
            sa.Column("resource_allowlist_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("prompt_allowlist_json", sa.Text(), nullable=False, server_default="[]")
        )

    # Before this migration, an empty tool allowlist meant "all tools".
    op.execute(
        "UPDATE mcp_server_configs SET legacy_all_tools = 1 "
        "WHERE tool_allowlist_json IS NULL OR tool_allowlist_json = '[]'"
    )

    op.create_table(
        "mcp_runtime_states",
        sa.Column(
            "server_config_id",
            sa.String(36),
            sa.ForeignKey("mcp_server_configs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="stopped"),
        sa.Column("connected_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("trashed_at", sa.DateTime(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("server_info_json", sa.Text(), nullable=True),
        sa.Column("capabilities_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "installed_skills",
        sa.Column("name", sa.String(255), primary_key=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("resolved_revision", sa.String(255), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("installed_path", sa.String(1000), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("installed_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("installed_skills")
    op.drop_table("mcp_runtime_states")
    with op.batch_alter_table("mcp_server_configs") as batch:
        batch.drop_column("prompt_allowlist_json")
        batch.drop_column("resource_allowlist_json")
        batch.drop_column("legacy_all_tools")
        batch.drop_column("secret_refs_json")
        batch.drop_column("env_json")
        batch.drop_column("url")
        batch.alter_column("command", existing_type=sa.String(500), nullable=False)
        batch.drop_column("transport")
