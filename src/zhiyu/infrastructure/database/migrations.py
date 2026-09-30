"""Alembic configuration and migration runner."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from filelock import FileLock

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
        command.upgrade(migration_config(database_url), "head")
