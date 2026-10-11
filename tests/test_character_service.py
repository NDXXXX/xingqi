"""角色应用服务测试。"""

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.characters import CharacterService
from zhiyu.application.memories import MemoryService
from zhiyu.core.memory.store import MemoryStore
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.models import Character, Conversation, Identity, Memory, Message
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository


def _service() -> tuple[CharacterService, sessionmaker]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return CharacterService(session_factory=factory), factory


def test_create_then_list():
    service, _ = _service()

    created = service.create(name="Luna", personality="温柔", speaking_style="简短口语")

    assert created.id
    assert created.has_system_prompt is False
    assert [item.name for item in service.list()] == ["Luna"]


def test_list_is_sorted_by_name():
    service, _ = _service()

    service.create(name="B")
    service.create(name="A")

    assert [item.name for item in service.list()] == ["A", "B"]


def test_get_returns_none_for_unknown_id():
    service, _ = _service()

    assert service.get("missing") is None


def test_has_system_prompt_ignores_blank():
    service, _ = _service()

    created = service.create(name="Luna", system_prompt="   ")

    assert created.has_system_prompt is False


def test_delete_missing_raises_configuration_error():
    service, _ = _service()

    with pytest.raises(ValueError):
        service.delete("missing")


def test_delete_removes_character():
    service, _ = _service()
    created = service.create(name="Luna")

    service.delete(created.id)

    assert service.list() == []


def test_current_for_conversation_is_none_before_assignment():
    service, factory = _service()
    with factory() as db:
        conversation = ConversationRepository().create(db, title="chat", channel="local")

    assert service.current_for_conversation(conversation.id) is None


def test_assign_to_conversation():
    service, factory = _service()
    created = service.create(name="Luna")
    with factory() as db:
        conversation = ConversationRepository().create(db, title="chat", channel="local")

    service.assign_to_conversation(conversation.id, created.id)

    current = service.current_for_conversation(conversation.id)
    assert current is not None
    assert current.name == "Luna"


def test_assign_rejects_unknown_character():
    service, factory = _service()
    with factory() as db:
        conversation = ConversationRepository().create(db, title="chat", channel="local")

    with pytest.raises(ValueError):
        service.assign_to_conversation(conversation.id, "missing")


def test_character_profile_fields_persist():
    service, _ = _service()
    character = service.create(
        name="编程助手", opening_message="你好", world_setting="现实世界",
        initial_scene="工作台", behavior_preferences="先给结论",
    )

    assert character.opening_message == "你好"
    assert character.world_setting == "现实世界"
    assert character.initial_scene == "工作台"
    assert character.behavior_preferences == "先给结论"


def test_character_template_round_trip_keeps_role_data_only(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    service = CharacterService(session_factory=factory, avatar_dir=tmp_path / "avatars", memory_store=MemoryStore(tmp_path / "memory"))
    original = service.create(
        name="夜航", personality="冷静", opening_message="晚上好", world_setting="近未来",
        initial_scene="观测站", behavior_preferences="先问清目标",
    )
    service.upload_avatar(original.id, "image/png", b"\x89PNG\r\n\x1a\nimage")

    template = service.export_template(original.id)
    assert "conversations" not in template
    assert "memories" not in template
    assert "api_key" not in str(template).lower()
    imported, warning = service.import_template(template)

    assert warning is None
    assert imported.id != original.id
    assert imported.personality == "冷静"
    assert imported.opening_message == "晚上好"
    assert imported.avatar != original.avatar
    assert service.avatar_path(imported.id).read_bytes().endswith(b"image")


def test_character_template_rejects_unknown_fields_and_invalid_avatar(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    service = CharacterService(session_factory=sessionmaker(bind=engine), memory_store=MemoryStore(tmp_path / "memory"))
    character = {key: None for key in {
        "name", "description", "personality", "background", "speaking_style", "system_prompt",
        "opening_message", "world_setting", "initial_scene", "behavior_preferences",
    }}
    character["name"] = "角色"
    template = {"format": "xingqi-character-template", "version": 1, "character": character, "default_model": None, "avatar": None}
    with pytest.raises(ValueError, match="字段不符合"):
        service.import_template({**template, "messages": []})
    with pytest.raises(ValueError, match="头像仅支持"):
        service.import_template({**template, "avatar": {"mime_type": "image/png", "data": "bm90LWltYWdl"}})


def test_delete_cascades_role_data_and_preserves_other_identity(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    store = MemoryStore(tmp_path / "memory")
    service = CharacterService(factory, avatar_dir=tmp_path / "avatars", memory_store=store)
    character = service.create(name="要删除的角色")
    MemoryService(factory, store, character.id).add(type="fact", content="角色专属经历")
    shared = MemoryService(factory, store).add(type="preference", content="用户喜欢简洁回答")
    with factory() as db:
        conversation = ConversationRepository().create(
            db, title="角色会话", channel="local", character_id=character.id
        )
        conversation_id = conversation.id
        MessageRepository().create(db, conversation_id=conversation.id, role="user", content="你好")
        role_identity = IdentityRepository().for_agent(db, character.id).id
        shared_identity = IdentityRepository().local(db).id

    service.delete(character.id)

    with factory() as db:
        assert db.get(Character, character.id) is None
        assert db.get(Conversation, conversation_id) is None
        assert db.get(Identity, role_identity) is None
        assert db.get(Identity, shared_identity) is not None
        assert db.get(Memory, shared.id) is not None
        assert db.scalars(select(Message).where(Message.conversation_id == conversation_id)).all() == []
    assert not store.vault_dir(character.id).exists()
    assert not (store.dir / ".deleting" / character.id).exists()


def test_avatar_validation_and_cleanup(tmp_path):
    service, factory = _service()
    character = service.create(name="有头像")
    service.avatar_dir = tmp_path / "avatars"
    with pytest.raises(ValueError, match="仅支持"):
        service.upload_avatar(character.id, "image/svg+xml", b"<svg/>")
    updated = service.upload_avatar(character.id, "image/png", b"\x89PNG\r\n\x1a\ncontent")
    path = service.avatar_path(character.id)
    assert updated.avatar and path and path.is_file()
    service.clear_avatar(character.id)
    assert service.avatar_path(character.id) is None
    assert not path.exists()


def test_interrupted_role_delete_restores_vault_when_role_remains(tmp_path):
    service, factory = _service()
    service.memory_store = MemoryStore(tmp_path / "memory")
    character = service.create(name="恢复中的角色")
    vault = service.memory_store.vault_dir(character.id)
    vault.mkdir(parents=True)
    (vault / "USER.md").write_text("角色记忆", encoding="utf-8")
    service.memory_store.quarantine_identity(character.id)

    CharacterService.recover_deletions(factory, service.memory_store, tmp_path / "avatars")

    assert (vault / "USER.md").read_text(encoding="utf-8") == "角色记忆"
    assert not (service.memory_store.dir / ".deleting" / character.id).exists()
