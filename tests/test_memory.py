"""Memory 检索与提取测试。"""

from zhiyu.infrastructure.database.models import Memory
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.core.memory.extractor import parse_candidates
from zhiyu.core.memory.retriever import retrieve


def _memory(content: str, importance: float = 0.5, type: str = "fact") -> Memory:
    return Memory(
        id="m", user_id=None, type=type, content=content, importance=importance, status="active"
    )


def test_retrieve_ranks_relevant_first():
    memories = [
        _memory("用户在开发桌面 AI 项目"),
        _memory("用户喜欢喝咖啡"),
    ]
    result = retrieve("继续搞桌面 AI 项目", memories)
    assert result and result[0].content == "用户在开发桌面 AI 项目"


def test_retrieve_top_k():
    memories = [_memory("用户喜欢咖啡"), _memory("用户喜欢茶"), _memory("用户喜欢牛奶")]
    result = retrieve("你喜欢咖啡吗", memories, top_k=1)
    assert len(result) == 1
    assert result[0].content == "用户喜欢咖啡"


def test_retrieve_no_match():
    assert retrieve("今天天气如何", [_memory("用户喜欢咖啡")]) == []


def test_parse_candidates_with_fence():
    text = '```json\n[{"type": "preference", "content": "用户喜欢咖啡"}]\n```'
    assert parse_candidates(text) == [{"type": "preference", "content": "用户喜欢咖啡"}]


def test_parse_candidates_plain():
    assert parse_candidates('[{"type": "fact", "content": "用户在北京"}]') == [
        {"type": "fact", "content": "用户在北京"}
    ]


def test_parse_candidates_invalid():
    assert parse_candidates("没有可提取的内容") == []
    assert parse_candidates('[{"type": "unknown", "content": "x"}]') == []


def test_memories_are_isolated_by_identity():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from zhiyu.infrastructure.database import models  # noqa: F401
    from zhiyu.infrastructure.database.db import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    identities = IdentityRepository()
    repo = MemoryRepository()
    local = identities.local(db)
    qq = identities.get_or_create(db, "qq", "10001")
    repo.create(db, type="fact", content="桌面秘密", identity_id=local.id)
    repo.create(db, type="fact", content="QQ 秘密", identity_id=qq.id)
    repo.create(db, type="fact", content="共享信息", identity_id=local.id, shared=True)

    assert {memory.content for memory in repo.list(db, local.id)} == {"桌面秘密", "共享信息"}
    assert {memory.content for memory in repo.list(db, qq.id)} == {"QQ 秘密", "共享信息"}
    db.close()
