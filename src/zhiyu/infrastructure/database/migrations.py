"""Alembic configuration and migration runner."""

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from filelock import FileLock
from sqlalchemy.engine import make_url

from zhiyu.infrastructure.config.settings import settings


MIGRATIONS_DIR = Path(__file__).with_name("alembic")


def migration_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url or settings.database_url)
    return config


def upgrade_database(database_url: str | None = None) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(settings.data_dir / ".migration.lock", timeout=30):
        config = migration_config(database_url)
        url = make_url(config.get_main_option("sqlalchemy.url"))
        if url.drivername == "sqlite" and url.database not in (None, "", ":memory:"):
            database_path = Path(url.database).expanduser().resolve()
            current = _current_revision(database_path)
            head = ScriptDirectory.from_config(config).get_current_head()
            if database_path.exists() and current != head:
                is_default = (
                    database_url is None
                    or database_path == settings.database_path.resolve()
                )
                memory_dir = (
                    settings.memory_dir
                    if is_default
                    else None
                )
                backup_database(
                    database_path,
                    memory_dir,
                    (settings.data_dir if is_default else database_path.parent)
                    / "backups",
                    revision=current,
                )
        command.upgrade(config, "head")


def _current_revision(database_path: Path) -> str | None:
    try:
        with sqlite3.connect(database_path) as connection:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            return str(row[0]) if row else None
    except sqlite3.Error:
        return None


def backup_database(
    database_path: Path,
    memory_dir: Path | None,
    backup_root: Path,
    *,
    revision: str | None,
) -> Path:
    """在迁移前创建一致的 SQLite 快照和可读记忆文件副本。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_root / f"{stamp}-{uuid4().hex[:8]}"
    destination.mkdir(parents=True, exist_ok=False)
    database_backup = destination / database_path.name
    try:
        with sqlite3.connect(database_path) as source, sqlite3.connect(
            database_backup
        ) as target:
            source.backup(target)
        if memory_dir is not None and memory_dir.exists():
            shutil.copytree(memory_dir, destination / "memory")
        (destination / "manifest.json").write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source_database": str(database_path),
                    "revision": revision or "legacy",
                    "memory_included": bool(memory_dir and memory_dir.exists()),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination
