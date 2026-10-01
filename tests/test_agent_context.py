"""Agent 入口共享上下文与工具组装测试。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.core.agent.context import build_tool_registry, trim_messages, with_agent_context
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.character_repository import CharacterRepository
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_build_tool_registry_contains_builtins():
    assert set(build_tool_registry().names()) >= {"calculator", "datetime"}


def test_with_agent_context_injects_character_and_memory():
    db = _session()
    identity = IdentityRepository().local(db)
    character = CharacterRepository().create(db, name="Luna", personality="温柔")
    conversation = ConversationRepository().create(
        db, title="chat", channel="local", character_id=character.id, identity_id=identity.id
    )
    MemoryRepository().create(
        db, type="preference", content="用户喜欢咖啡", identity_id=identity.id
    )

    messages = with_agent_context(
        db,
        conversation,
        "我喜欢什么咖啡？",
        [{"role": "user", "content": "我喜欢什么咖啡？"}],
    )

    assert messages[0]["role"] == "system"
    assert "Luna" in messages[0]["content"]
    assert "用户喜欢咖啡" in messages[0]["content"]
    db.close()


def test_trim_messages_keeps_system_and_recent_history():
    messages = [
        {"role": "system", "content": "必须保留"},
        {"role": "user", "content": "旧消息" * 200},
        {"role": "assistant", "content": "旧回复" * 200},
        {"role": "user", "content": "最新问题"},
    ]

    trimmed = trim_messages(messages, context_window=400, max_output_tokens=100)

    assert trimmed[0] == messages[0]
    assert trimmed[-1] == messages[-1]
    assert messages[1] not in trimmed
