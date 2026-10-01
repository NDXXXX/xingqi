"""记忆生命周期和本地管理服务测试。"""

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.memories import MemoryService
from zhiyu.core.memory.manager import MemoryManager
from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository


class OperationProvider(AIProvider):
    def __init__(self, operations):
        super().__init__(None)
        self.operations = operations

    async def chat(self, messages, tools=None, stream=False, **kwargs):
        return LLMResponse(content=json.dumps(self.operations, ensure_ascii=False))


def _database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _source(factory, text):
    with factory() as db:
        identity = IdentityRepository().local(db)
        conversation = ConversationRepository().create(
            db, title="chat", channel="local", identity_id=identity.id
        )
        message = MessageRepository().create(
            db, conversation_id=conversation.id, role="user", content=text
        )
        return identity.id, message.id


async def test_replace_preserves_old_memory_and_source():
    factory = _database()
    identity_id, source_id = _source(factory, "最近戒咖啡了，以后别推荐")
    with factory() as db:
        old = MemoryRepository().create(
            db, type="preference", content="用户喜欢咖啡", identity_id=identity_id
        )
        db.commit()
        old_id = old.id
        provider = OperationProvider(
            [
                {
                    "action": "replace",
                    "target_id": old_id,
                    "type": "preference",
                    "content": "用户已戒咖啡，不希望收到咖啡推荐",
                    "evidence": "最近戒咖啡了，以后别推荐",
                }
            ]
        )

        await MemoryManager().extract_and_save(
            db,
            provider,
            "test",
            "最近戒咖啡了，以后别推荐",
            "好的",
            identity_id,
            user_message_id=source_id,
        )

        all_memories = MemoryRepository().list_owned(db, identity_id, statuses=None)
        active = next(item for item in all_memories if item.status == "active")
        replaced = next(item for item in all_memories if item.id == old_id)
        assert replaced.status == "superseded"
        assert active.supersedes_id == old_id
        assert active.source_message_id == source_id


async def test_operation_without_user_evidence_is_ignored():
    factory = _database()
    identity_id, source_id = _source(factory, "今天天气不错")
    provider = OperationProvider(
        [
            {
                "action": "add",
                "type": "goal",
                "content": "用户准备学习 Rust",
                "evidence": "学习 Rust",
            }
        ]
    )
    with factory() as db:
        changed = await MemoryManager().extract_and_save(
            db,
            provider,
            "test",
            "今天天气不错",
            "你可以学习 Rust",
            identity_id,
            user_message_id=source_id,
        )
        assert changed == []
        assert MemoryRepository().list_owned(db, identity_id) == []


async def test_complete_is_scoped_to_current_identity():
    factory = _database()
    identity_id, source_id = _source(factory, "这个项目已经完成了")
    with factory() as db:
        other = IdentityRepository().get_or_create(db, "qq", "other-user")
        own_goal = MemoryRepository().create(
            db, type="goal", content="完成 MCP 接入", identity_id=identity_id
        )
        other_goal = MemoryRepository().create(
            db, type="goal", content="另一个人的目标", identity_id=other.id
        )
        db.commit()
        provider = OperationProvider(
            [
                {
                    "action": "complete",
                    "target_id": own_goal.id,
                    "evidence": "这个项目已经完成了",
                },
                {
                    "action": "complete",
                    "target_id": other_goal.id,
                    "evidence": "这个项目已经完成了",
                },
            ]
        )

        # 同一目标 ID 只能操作一次，但不同身份的目标不会出现在候选中。
        await MemoryManager().extract_and_save(
            db,
            provider,
            "test",
            "这个项目已经完成了",
            "收到",
            identity_id,
            user_message_id=source_id,
        )

        assert MemoryRepository().get(db, own_goal.id).status == "completed"
        assert MemoryRepository().get(db, other_goal.id).status == "active"


def test_memory_service_edit_complete_and_forget():
    factory = _database()
    service = MemoryService(factory)
    old = service.add(type="preference", content="用户喜欢咖啡")
    corrected = service.edit(old.id, content="用户不喝咖啡")

    assert service.get(old.id).status == "superseded"
    assert corrected.supersedes_id == old.id
    assert [item.content for item in service.list()] == ["用户不喝咖啡"]

    goal = service.add(type="goal", content="完成 MCP 接入")
    service.complete(goal.id)
    assert service.get(goal.id).status == "completed"
    assert all(item.id != goal.id for item in service.list())

    service.forget(corrected.id)
    assert service.get(corrected.id) is None


def test_memory_repository_rejects_unscoped_list():
    factory = _database()
    with factory() as db:
        try:
            MemoryRepository().list_visible(db, "")
        except ValueError as exc:
            assert "身份" in str(exc)
        else:
            raise AssertionError("空身份不应读取记忆")
