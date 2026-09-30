"""Database engine and session factory."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from zhiyu.infrastructure.config.settings import settings

settings.database_path.parent.mkdir(parents=True, exist_ok=True)

_sqlite = settings.database_url.startswith("sqlite:")
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 5} if _sqlite else {},
)


if _sqlite:
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Base class for ORM models."""
