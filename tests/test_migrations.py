"""Alembic 对已有 MVP 数据库的兼容迁移测试。"""

from alembic import command
from sqlalchemy import create_engine, inspect, text

from zhiyu.infrastructure.database.migrations import migration_config


def test_upgrade_preserves_legacy_data(tmp_path):
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE conversations ("
            "id VARCHAR(36) PRIMARY KEY, title VARCHAR(255) NOT NULL, character_id VARCHAR(36), "
            "channel VARCHAR(32) NOT NULL, external_user_id VARCHAR(255), model_id VARCHAR(255), "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO conversations VALUES "
            "('c1', '保留我', NULL, 'desktop', NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        connection.execute(text(
            "CREATE TABLE messages (id VARCHAR(36) PRIMARY KEY, conversation_id VARCHAR(36) NOT NULL, "
            "role VARCHAR(16) NOT NULL, content TEXT NOT NULL, created_at DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "CREATE TABLE providers (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, "
            "provider_type VARCHAR(32) NOT NULL, api_key_ref VARCHAR(255), base_url VARCHAR(255), "
            "enabled BOOLEAN NOT NULL)"
        ))
        connection.execute(text(
            "CREATE TABLE model_configs (id VARCHAR(36) PRIMARY KEY, provider_id VARCHAR(36) NOT NULL, "
            "model_name VARCHAR(255) NOT NULL, display_name VARCHAR(255) NOT NULL, "
            "supports_tools BOOLEAN NOT NULL, supports_streaming BOOLEAN NOT NULL, enabled BOOLEAN NOT NULL)"
        ))
        connection.execute(text(
            "CREATE TABLE characters (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, "
            "avatar VARCHAR(255), description TEXT, personality TEXT, background TEXT, speaking_style TEXT, "
            "system_prompt TEXT, default_model_id VARCHAR(255), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "CREATE TABLE memories (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36), type VARCHAR(32) NOT NULL, "
            "content TEXT NOT NULL, importance FLOAT NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO memories VALUES "
            "('m1', NULL, 'preference', '保留这条记忆', 0.5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))

    config = migration_config(f"sqlite:///{database}")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT title FROM conversations WHERE id='c1'")) == "保留我"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008_memory_jobs"
        assert connection.scalar(text("SELECT channel FROM conversations WHERE id='c1'")) == "local"
        memory = connection.execute(text(
            "SELECT content, status, origin FROM memories WHERE id='m1'"
        )).one()
        assert tuple(memory) == ("保留这条记忆", "active", "legacy")
    tables = set(inspect(engine).get_table_names())
    assert "app_settings" in tables
    assert {"identities", "channel_configs", "mcp_server_configs", "memory_jobs"} <= tables
    assert {"created_at", "updated_at"} <= {column["name"] for column in inspect(engine).get_columns("providers")}
    assert {"status", "origin", "source_message_id", "supersedes_id"} <= {
        column["name"] for column in inspect(engine).get_columns("memories")
    }


def test_reverse_upgrade_disables_old_qq_endpoint(tmp_path):
    database = tmp_path / "forward.db"
    config = migration_config(f"sqlite:///{database}")
    command.upgrade(config, "0004_agent_runs")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO channel_configs "
            "(id, channel, name, endpoint, secret_ref, enabled, auto_connect, created_at, updated_at) "
            "VALUES ('qq-config', 'qq', 'QQ', 'ws://localhost:3001', 'saved-secret', 1, 1, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT enabled, auto_connect, endpoint, secret_ref FROM channel_configs WHERE channel='qq'"
        )).one()
        assert tuple(row) == (0, 0, "ws://localhost:3001", "saved-secret")


def test_memory_lifecycle_migration_can_round_trip(tmp_path):
    database = tmp_path / "round-trip.db"
    config = migration_config(f"sqlite:///{database}")
    command.upgrade(config, "head")
    command.downgrade(config, "0006_local_identity")

    engine = create_engine(f"sqlite:///{database}")
    columns = {column["name"] for column in inspect(engine).get_columns("memories")}
    assert "status" not in columns

    command.upgrade(config, "head")
    columns = {column["name"] for column in inspect(engine).get_columns("memories")}
    assert {"status", "origin", "source_message_id", "supersedes_id"} <= columns
