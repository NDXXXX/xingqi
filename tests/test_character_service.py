"""角色应用服务测试。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.characters import CharacterService
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository


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
