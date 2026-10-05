"""深度召回（Lane 2）与按会话遗忘测试。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.memories import MemoryService
from zhiyu.core.memory.deep_recall import deep_recall, has_recall_intent, is_forgotten
from zhiyu.core.memory.store import MemoryStore
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository


def _database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_has_recall_intent():
    assert has_recall_intent("我上次说的那个项目是什么")
    assert has_recall_intent("你还记得我之前说过吗")
    assert not has_recall_intent("今天天气怎么样")


def test_deep_recall_returns_episodic_and_history():
    factory = _database()
    with factory() as db:
        identity = IdentityRepository().local(db)
        conversation = ConversationRepository().create(
            db, title="chat", channel="local", identity_id=identity.id
        )
        MessageRepository().create(
            db, conversation_id=conversation.id, role="user", content="我最近开始学 Rust"
        )
        MemoryRepository().create(
            db,
            type="goal",
            content="用户正在学习 Rust",
            identity_id=identity.id,
            tier="episodic",
            trust="agent",
            source_kind="message",
            promotion_status="pending",
            conversation_id=conversation.id,
        )
        db.commit()
        identity_id = identity.id

        result = deep_recall(db, identity_id, "我上次说的 Rust 学习", exclude_conversation_id=conversation.id)
        assert result is not None
        assert "Rust" in result


def test_runtime_deep_recall_does_not_search_other_sessions():
    factory = _database()
    with factory() as db:
        identity = IdentityRepository().local(db)
        current = ConversationRepository().create(
            db, title="current", channel="local", identity_id=identity.id
        )
        other = ConversationRepository().create(
            db, title="other", channel="qq", identity_id=identity.id
        )
        MessageRepository().create(
            db,
            conversation_id=other.id,
            role="user",
            content="我上次提到的火星殖民项目",
        )
        db.commit()

        result = deep_recall(
            db,
            identity.id,
            "我上次提到的火星殖民项目",
            current_conversation_id=current.id,
        )

    assert result is None


def test_forget_conversation_deletes_and_tombstones(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity = IdentityRepository().local(db)
        conversation = ConversationRepository().create(
            db, title="chat", channel="local", identity_id=identity.id
        )
        path = store.daily_path()
        entry = store.append(path, "用户正在学习 Rust", meta={"type": "goal"})
        MemoryRepository().create(
            db,
            type="goal",
            content=entry.content,
            identity_id=identity.id,
            tier="episodic",
            trust="agent",
            source_kind="message",
            promotion_status="pending",
            conversation_id=conversation.id,
            file_path=path.name,
            line_start=entry.line_start,
            line_end=entry.line_end,
            content_hash=entry.hash,
        )
        db.commit()
        identity_id = identity.id
        conversation_id = conversation.id

    count = MemoryService(factory, store=store).forget_conversation(conversation_id)
    assert count == 1

    with factory() as db:
        assert MemoryRepository().list_owned(db, identity_id, tier="episodic", statuses=None) == []
        assert is_forgotten(db, conversation_id) is True
        assert "用户正在学习 Rust" not in (tmp_path / path.name).read_text(encoding="utf-8")
