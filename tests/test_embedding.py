"""语义检索（embedding + 混合检索）测试。"""

from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.core.memory.retriever import hybrid_retrieve
from zhiyu.core.providers.embedding import embed_text_async, load_config, save_config
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.models import MemoryEmbedding
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository


def _database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_embedding_config_round_trip():
    factory = _database()
    with factory() as db:
        assert load_config(db) is None
        save_config(db, base_url="https://api.example.com/v1", model="text-embed-3-small", api_key_ref="env:KEY")
    with factory() as db:
        config = load_config(db)
        assert config is not None
        assert config.base_url == "https://api.example.com/v1"
        assert config.model == "text-embed-3-small"
        assert config.api_key_ref == "env:KEY"


def test_hybrid_retrieve_ranks_by_vector(monkeypatch):
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        coffee = MemoryRepository().create(
            db, type="fact", content="用户喜欢咖啡", identity_id=identity_id
        )
        tea = MemoryRepository().create(
            db, type="fact", content="用户喜欢喝茶", identity_id=identity_id
        )
        db.commit()
        coffee_id, tea_id = coffee.id, tea.id

    monkeypatch.setattr(
        "zhiyu.core.memory.retriever.embed_text", lambda db, q: ("fake", [1.0, 0.0])
    )
    monkeypatch.setattr(
        "zhiyu.core.memory.retriever.load_vectors",
        lambda db, ids, **kwargs: {coffee_id: [1.0, 0.0], tea_id: [0.0, 1.0]},
    )

    with factory() as db:
        memories = MemoryRepository().list_owned(db, identity_id, tier="core")
        result = hybrid_retrieve(db, "饮品", memories, top_k=2)
        assert result[0].id == coffee_id


def test_hybrid_retrieve_falls_back_to_lexical(monkeypatch):
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        coffee = MemoryRepository().create(
            db, type="fact", content="用户喜欢咖啡", identity_id=identity_id
        )
        MemoryRepository().create(db, type="fact", content="用户喜欢喝茶", identity_id=identity_id)
        db.commit()
        coffee_id = coffee.id

    monkeypatch.setattr("zhiyu.core.memory.retriever.embed_text", lambda db, q: None)
    monkeypatch.setattr(
        "zhiyu.core.memory.retriever.load_vectors", lambda db, ids, **kwargs: {}
    )

    with factory() as db:
        memories = MemoryRepository().list_owned(db, identity_id, tier="core")
        result = hybrid_retrieve(db, "咖啡", memories, top_k=1)
        assert result[0].id == coffee_id


async def test_async_query_embedding_uses_short_lived_cache(monkeypatch):
    factory = _database()
    calls = 0

    async def fake_embed(*args, **kwargs):
        nonlocal calls
        calls += 1
        return [[1.0, 2.0]]

    monkeypatch.setenv("EMBED_CACHE_TEST", "key")
    monkeypatch.setattr("zhiyu.core.providers.embedding.embed_async", fake_embed)
    with factory() as db:
        save_config(
            db,
            base_url="https://example.invalid/v1",
            model="cache-model",
            api_key_ref="env:EMBED_CACHE_TEST",
        )
        first = await embed_text_async(db, "同一个查询")
        second = await embed_text_async(db, "同一个查询")

    assert first == second == ("cache-model", [1.0, 2.0])
    assert calls == 1


def test_malformed_stored_vector_falls_back_without_breaking_recall(monkeypatch):
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        coffee = MemoryRepository().create(
            db, type="fact", content="用户喜欢咖啡", identity_id=identity_id
        )
        db.add(
            MemoryEmbedding(
                id=str(uuid4()),
                memory_id=coffee.id,
                model="broken-model",
                vector_json='["not-a-number", 1.0]',
            )
        )
        db.commit()
        coffee_id = coffee.id

    monkeypatch.setattr(
        "zhiyu.core.memory.retriever.embed_text",
        lambda db, q: ("broken-model", [1.0, 0.0]),
    )
    with factory() as db:
        memories = MemoryRepository().list_owned(db, identity_id, tier="core")
        result = hybrid_retrieve(db, "咖啡", memories, top_k=1)

    assert [item.id for item in result] == [coffee_id]
