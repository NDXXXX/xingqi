"""记忆生命周期和本地管理服务测试。"""

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.memories import MemoryService
from zhiyu.core.memory.manager import MemoryManager
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository


class ObservationProvider(AIProvider):
    def __init__(self, observations):
        super().__init__(None)
        self.observations = observations

    async def chat(self, messages, tools=None, stream=False, **kwargs):
        return LLMResponse(content=json.dumps(self.observations, ensure_ascii=False))


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
        return identity.id, message.id, conversation.id


async def test_observation_is_saved_as_episodic(tmp_path):
    factory = _database()
    identity_id, source_id, conversation_id = _source(factory, "最近开始学 Rust")
    provider = ObservationProvider(
        [{"type": "goal", "content": "用户正在学习 Rust", "evidence": "最近开始学 Rust"}]
    )
    with factory() as db:
        changed = await MemoryManager(store=MemoryStore(tmp_path)).extract_and_save(
            db,
            provider,
            "test",
            "最近开始学 Rust",
            "好的",
            identity_id,
            user_message_id=source_id,
        )
        assert len(changed) == 1
        memory = changed[0]
        assert memory.tier == "episodic"
        assert memory.trust == "agent"
        assert memory.promotion_status == "pending"
        assert memory.conversation_id == conversation_id
        assert memory.file_path is not None
        assert memory.content_hash is not None
        assert (tmp_path / memory.file_path).exists()


async def test_observation_without_user_evidence_is_ignored(tmp_path):
    factory = _database()
    identity_id, source_id, _ = _source(factory, "今天天气不错")
    provider = ObservationProvider(
        [{"type": "goal", "content": "用户准备学习 Rust", "evidence": "学习 Rust"}]
    )
    with factory() as db:
        changed = await MemoryManager(store=MemoryStore(tmp_path)).extract_and_save(
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


def test_memory_service_edit_complete_and_forget(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    service = MemoryService(factory, store=store)
    old = service.add(type="preference", content="用户喜欢咖啡")
    corrected = service.edit(old.id, content="用户不喝咖啡")

    assert service.get(old.id).status == "superseded"
    assert corrected.supersedes_id == old.id
    assert [item.content for item in service.list()] == ["用户不喝咖啡"]

    with factory() as db:
        identity_id = IdentityRepository().local(db).id
    user_text = store.user_path_for(identity_id).read_text(encoding="utf-8")
    assert "用户喜欢咖啡" not in user_text
    assert "用户不喝咖啡" in user_text

    goal = service.add(type="goal", content="完成 MCP 接入")
    service.complete(goal.id)
    assert service.get(goal.id).status == "completed"
    assert all(item.id != goal.id for item in service.list())

    service.forget(corrected.id)
    assert service.get(corrected.id) is None


def test_memory_service_add_routes_core_types_to_files(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    service = MemoryService(factory, store=store)
    service.add(type="preference", content="回答时优先给结论")
    service.add(type="fact", content="用户住在北京")

    with factory() as db:
        identity_id = IdentityRepository().local(db).id
    assert "回答时优先给结论" in store.user_path_for(identity_id).read_text(
        encoding="utf-8"
    )
    assert "用户住在北京" in store.core_path_for(identity_id).read_text(
        encoding="utf-8"
    )
    assert [item.tier for item in service.list()] == ["core", "core"]


def test_memory_index_and_export_stay_scoped_to_local_identity(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    service = MemoryService(factory, store=store)
    service.add(type="fact", content="本机用户的事实")
    with factory() as db:
        other = IdentityRepository().get_or_create(db, "qq", "other-user")
        other_id = other.id
    store.append(store.core_path_for(other_id), "其他身份的事实", meta={"type": "fact"})

    exported = service.export_files()
    assert any("本机用户的事实" in content for _, content in exported)
    assert all("其他身份的事实" not in content for _, content in exported)
    assert service.rebuild_index()["created"] >= 0
    assert [item.content for item in service.list()] == ["本机用户的事实"]


def test_forget_plan_is_read_only(tmp_path):
    factory = _database()
    service = MemoryService(factory, store=MemoryStore(tmp_path))
    memory = service.add(type="fact", content="仅用于预览删除")

    plan = service.plan_forget(memory_id=memory.id)

    assert plan["entries"][0]["action"] == "delete"
    assert service.get(memory.id) is not None


def test_memory_list_indexes_external_markdown_edit(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
    store.append(
        store.core_path_for(identity_id),
        "用户手工写入 Markdown 的事实",
        meta={"type": "fact"},
    )

    items = MemoryService(factory, store=store).list()

    assert [item.content for item in items] == ["用户手工写入 Markdown 的事实"]


def test_memory_repository_rejects_unscoped_list():
    factory = _database()
    with factory() as db:
        try:
            MemoryRepository().list_visible(db, "")
        except ValueError as exc:
            assert "身份" in str(exc)
        else:
            raise AssertionError("空身份不应读取记忆")
