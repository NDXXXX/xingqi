"""Memory index health state remains visible after synchronization failures."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import zhiyu.core.memory.indexer as indexer
from zhiyu.core.memory.store import MemoryStore
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository


def _session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_index_status_moves_from_ready_to_stale_on_sync_failure(tmp_path, monkeypatch):
    factory = _session_factory()
    store = MemoryStore(tmp_path / "memory")
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        path = store.core_path_for(identity_id)
        path.parent.mkdir(parents=True)
        path.write_text("# Memory\n- 用户喜欢咖啡 <!-- id=entry-1 -->\n", encoding="utf-8")
        indexer.rebuild_index(db, store, identity_id)
        ready = indexer.get_index_status(db, identity_id)
        assert ready["status"] == "ready"
        assert ready["last_success_at"]

    def fail_sync(*_args, **_kwargs):
        raise RuntimeError(f"private path: {tmp_path}")

    monkeypatch.setattr(indexer, "_sync_changed_index", fail_sync)
    with factory() as db:
        with pytest.raises(RuntimeError):
            indexer.sync_changed_index(db, store, identity_id)
        stale = indexer.get_index_status(db, identity_id)

    assert stale["status"] == "stale"
    assert stale["last_success_at"] == ready["last_success_at"]
    assert "private path" not in stale["error"]
    assert str(tmp_path) not in stale["error"]
