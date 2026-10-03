"""语义检索（embedding + 混合检索）测试。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.core.memory.retriever import hybrid_retrieve
from zhiyu.core.providers.embedding import load_config, save_config
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
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
        lambda db, ids: {coffee_id: [1.0, 0.0], tea_id: [0.0, 1.0]},
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
    monkeypatch.setattr("zhiyu.core.memory.retriever.load_vectors", lambda db, ids: {})

    with factory() as db:
        memories = MemoryRepository().list_owned(db, identity_id, tier="core")
        result = hybrid_retrieve(db, "咖啡", memories, top_k=1)
        assert result[0].id == coffee_id
