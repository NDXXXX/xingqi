"""Explicit memory tools only expose live entries in the requesting identity."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.core.memory.indexer import rebuild_index
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.tools.memory import MemoryGetTool, MemorySearchTool
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository


async def test_memory_tools_respect_identity_and_live_file(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    store = MemoryStore(tmp_path)
    with sessions() as db:
        identities = IdentityRepository()
        local = identities.local(db)
        other = identities.get_or_create(db, "qq", "other")
        own = store.append(store.daily_path(identity_id=local.id), "用户的代号是星河")
        store.append(store.daily_path(identity_id=other.id), "用户的代号是月海")
        rebuild_index(db, store, local.id)
        rebuild_index(db, store, other.id)
        own_memory = next(
            item for item in MemoryRepository().list_owned(db, local.id)
            if item.content == "用户的代号是星河"
        )
        foreign_memory = next(
            item for item in MemoryRepository().list_owned(db, other.id)
            if item.content == "用户的代号是月海"
        )
        own_id, foreign_id = own_memory.id, foreign_memory.id

    search = MemorySearchTool(sessions, local.id, store)
    get = MemoryGetTool(sessions, local.id, store)
    result = await search.execute("代号星河")
    assert any(
        item["id"] == own_id and "未核实的外部资料" in item["warning"]
        for item in result["results"]
    )
    assert all(item["id"] != foreign_id for item in result["results"])
    detail = await get.execute(own_id)
    assert detail["content"] == "用户的代号是星河"
    assert "未核实的外部资料" in detail["warning"]
    assert await get.execute(foreign_id) == {"found": False}

    store.remove_by_id(store.daily_path(identity_id=local.id), own.id)
    assert await get.execute(own_id) == {"found": False}
