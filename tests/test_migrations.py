"""Alembic 对已有 MVP 数据库的兼容迁移测试。"""

from alembic import command
from sqlalchemy import create_engine, inspect, text

from zhiyu.infrastructure.database.migrations import backup_database, migration_config


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
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0019_installed_skill_trash"
        assert connection.scalar(
            text("SELECT owner_user_id FROM channel_configs WHERE channel='qq'")
        ) is None
        assert connection.scalar(text("SELECT channel FROM conversations WHERE id='c1'")) == "local"
        memory = connection.execute(text(
            "SELECT content, status, origin FROM memories WHERE id='m1'"
        )).one()
        assert tuple(memory) == ("保留这条记忆", "active", "legacy")
    tables = set(inspect(engine).get_table_names())
    assert "app_settings" in tables
    assert {
        "identities",
        "channel_configs",
        "mcp_server_configs",
        "memory_jobs",
        "channel_events",
        "channel_deliveries",
        "channel_group_policies",
        "channel_media_assets",
        "conversation_summaries",
    } <= tables
    assert "tool_allowlist_json" in {
        column["name"] for column in inspect(engine).get_columns("mcp_server_configs")
    }
    assert {"parts_json", "source_event_id"} <= {
        column["name"] for column in inspect(engine).get_columns("messages")
    }
    assert "trashed_at" in {
        column["name"] for column in inspect(engine).get_columns("installed_skills")
    }
    assert {"account_id", "driver"} <= {
        column["name"] for column in inspect(engine).get_columns("channel_configs")
    }
    assert {"lease_owner", "lease_expires_at", "outbound_message_json"} <= {
        column["name"] for column in inspect(engine).get_columns("channel_events")
    }
    assert {"created_at", "updated_at"} <= {column["name"] for column in inspect(engine).get_columns("providers")}
    assert {"status", "origin", "source_message_id", "supersedes_id"} <= {
        column["name"] for column in inspect(engine).get_columns("memories")
    }
    assert {"tier", "trust", "source_kind", "observed_at", "file_path", "content_hash", "entry_key"} <= {
        column["name"] for column in inspect(engine).get_columns("memories")
    }
    assert {"memory_sources", "memory_recall_events", "memory_mutations"} <= tables


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


def test_identity_tombstones_downgrade_without_unique_conflict(tmp_path):
    database = tmp_path / "tombstone-round-trip.db"
    config = migration_config(f"sqlite:///{database}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identities "
                "(id, channel, external_user_id, display_name, created_at, updated_at) "
                "VALUES ('qq-identity', 'qq', '10001', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO forgotten_conversations "
                "(id, identity_id, conversation_id, created_at) VALUES "
                "('f-local', '00000000-0000-0000-0000-000000000001', 'same-conversation', CURRENT_TIMESTAMP), "
                "('f-qq', 'qq-identity', 'same-conversation', CURRENT_TIMESTAMP)"
            )
        )

    command.downgrade(config, "0012_forgotten_conversations")
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM forgotten_conversations "
                "WHERE conversation_id='same-conversation'"
            )
        ) == 1


def test_pre_migration_backup_contains_database_and_memory(tmp_path):
    database = tmp_path / "source.db"
    with create_engine(f"sqlite:///{database}").begin() as connection:
        connection.execute(text("CREATE TABLE sample (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO sample VALUES ('before')"))
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("- before\n", encoding="utf-8")

    backup = backup_database(
        database, memory_dir, tmp_path / "backups", revision="0012"
    )

    with create_engine(f"sqlite:///{backup / 'source.db'}").connect() as connection:
        assert connection.scalar(text("SELECT value FROM sample")) == "before"
    assert (backup / "memory" / "MEMORY.md").read_text(encoding="utf-8") == "- before\n"
    assert "0012" in (backup / "manifest.json").read_text(encoding="utf-8")
