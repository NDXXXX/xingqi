"""应用启动时执行数据库迁移。"""

from contextlib import contextmanager
import fcntl
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config

from ..config.settings import settings


@contextmanager
def _migration_lock():
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    with (settings.database_path.parent / ".migration.lock").open("w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def upgrade_database() -> None:
    if getattr(sys, "frozen", False):
        server_dir = Path(getattr(sys, "_MEIPASS"))
    else:
        server_dir = Path(__file__).resolve().parents[2]
    config = Config(str(server_dir / "alembic.ini"))
    config.set_main_option("script_location", str(server_dir / "migrations"))
    with _migration_lock():
        command.upgrade(config, "head")
