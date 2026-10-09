"""Give each character its own memory workspace and integration permissions."""

from alembic import op
import sqlalchemy as sa

revision = "0023_multi_agent"
down_revision = "0022_standing_intents"
branch_labels = None
depends_on = None


def _fts_triggers():
    op.execute("DELETE FROM memory_fts")
    op.execute("INSERT INTO memory_fts(rowid, memory_id, content) SELECT rowid, id, content FROM memories")
    op.execute("CREATE TRIGGER memories_fts_insert AFTER INSERT ON memories BEGIN INSERT INTO memory_fts(rowid, memory_id, content) VALUES (new.rowid, new.id, new.content); END")
    op.execute("CREATE TRIGGER memories_fts_update AFTER UPDATE OF content ON memories BEGIN DELETE FROM memory_fts WHERE rowid = old.rowid; INSERT INTO memory_fts(rowid, memory_id, content) VALUES (new.rowid, new.id, new.content); END")
    op.execute("CREATE TRIGGER memories_fts_delete AFTER DELETE ON memories BEGIN DELETE FROM memory_fts WHERE rowid = old.rowid; END")


def upgrade():
    op.add_column("identities", sa.Column("memory_reset_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE conversations SET character_id = NULL WHERE character_id NOT IN (SELECT id FROM characters)")
    with op.batch_alter_table("conversations") as batch:
        batch.create_foreign_key("fk_conversation_character", "characters", ["character_id"], ["id"], ondelete="RESTRICT")
    # Identity already denotes the persisted memory workspace. An agent gets a
    # distinct workspace; legacy memories remain in the default workspace.
    op.execute("INSERT INTO identities (id, channel, external_user_id, display_name, created_at, updated_at) SELECT id, 'agent', id, name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM characters WHERE id NOT IN (SELECT id FROM identities)")
    op.execute("UPDATE identities SET memory_reset_at = CURRENT_TIMESTAMP WHERE channel = 'agent'")
    op.execute("UPDATE conversations SET identity_id = character_id WHERE character_id IS NOT NULL")
    for table in ("memories", "memory_jobs", "mcp_server_configs"):
        with op.batch_alter_table(table, naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}) as batch:
            batch.add_column(sa.Column("character_id", sa.String(36), nullable=True))
            batch.create_foreign_key(f"fk_{table}_character", "characters", ["character_id"], ["id"], ondelete="RESTRICT")
            if table == "memories":
                batch.create_index("ix_memories_agent_status", ["identity_id", "character_id", "status"])
            if table == "mcp_server_configs":
                batch.drop_constraint("uq_mcp_server_configs_name", type_="unique")
    _fts_triggers()
    # Pending legacy character jobs must not import history into a new workspace.
    op.execute("UPDATE memory_jobs SET status = 'cancelled' WHERE user_message_id IN (SELECT messages.id FROM messages JOIN conversations ON conversations.id = messages.conversation_id WHERE conversations.character_id IS NOT NULL) AND status IN ('pending', 'processing')")
    op.create_index("uq_mcp_agent_name", "mcp_server_configs", ["character_id", "name"], unique=True, sqlite_where=sa.text("character_id IS NOT NULL"))
    op.create_index("uq_mcp_default_name", "mcp_server_configs", ["name"], unique=True, sqlite_where=sa.text("character_id IS NULL"))
    op.create_table("character_skills",
        sa.Column("character_id", sa.String(36), sa.ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("skill_name", sa.String(255), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.drop_table("standing_intents")


def downgrade():
    # Multiple agent configurations with the same name cannot be represented in
    # the legacy global namespace. Refuse before dropping data.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT name FROM mcp_server_configs GROUP BY name HAVING COUNT(*) > 1")).first():
        raise RuntimeError("存在同名智能体 MCP 配置，无法安全降级")
    from importlib import import_module
    import_module("zhiyu.infrastructure.database.alembic.versions.0022_standing_intents").upgrade()
    op.drop_table("character_skills")
    op.drop_index("uq_mcp_agent_name", table_name="mcp_server_configs")
    op.drop_index("uq_mcp_default_name", table_name="mcp_server_configs")
    for table in ("mcp_server_configs", "memory_jobs", "memories"):
        with op.batch_alter_table(table) as batch:
            if table == "memories":
                batch.drop_index("ix_memories_agent_status")
            batch.drop_constraint(f"fk_{table}_character", type_="foreignkey")
            batch.drop_column("character_id")
            if table == "mcp_server_configs":
                batch.create_unique_constraint("uq_mcp_server_configs_name", ["name"])
    _fts_triggers()
    with op.batch_alter_table("identities") as batch:
        batch.drop_column("memory_reset_at")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("fk_conversation_character", type_="foreignkey")
