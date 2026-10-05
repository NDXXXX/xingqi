"""Agent 入口共享上下文与工具组装测试。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import zhiyu.core.agent.context as context_module
from zhiyu.core.agent.context import (
    build_tool_registry,
    compact_messages,
    trim_messages,
    with_agent_context,
)
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.character_repository import CharacterRepository
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.integrations.skills.registry import SkillRegistry


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


def test_compact_messages_keeps_recent_round_and_summarizes_older_history():
    messages = [
        {"role": "system", "content": "必须保留"},
        {"role": "user", "content": "第一轮问题" * 40},
        {"role": "assistant", "content": "第一轮回答" * 40},
        {"role": "user", "content": "最新问题"},
    ]

    compacted, summary, source_count = compact_messages(
        messages,
        context_window=420,
        max_output_tokens=100,
    )

    assert compacted[0] == messages[0]
    assert any("较早会话摘要" in item["content"] for item in compacted)
    assert compacted[-1] == messages[-1]
    assert summary is not None and "第一轮" in summary
    assert source_count == 2


def test_context_compaction_persists_derived_summary():
    db = _session()
    identity = IdentityRepository().local(db)
    conversation = ConversationRepository().create(
        db,
        title="long chat",
        channel="local",
        identity_id=identity.id,
    )
    history = [
        {"role": "user", "content": "很早的问题" * 50},
        {"role": "assistant", "content": "很早的回答" * 50},
        {"role": "user", "content": "当前问题"},
    ]

    with_agent_context(
        db,
        conversation,
        "当前问题",
        history,
        context_window=420,
        max_output_tokens=100,
    )
    summary = db.get(models.ConversationSummary, conversation.id)

    assert summary is not None
    assert "很早" in summary.content
    assert summary.source_message_count == 2
    db.close()


def test_context_lists_skill_metadata_without_injecting_body(tmp_path, monkeypatch):
    skill_dir = tmp_path / "research"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: research\ndescription: 分析仓库结构\n---\n\n不要提前注入的完整正文",
        encoding="utf-8",
    )
    monkeypatch.setattr(context_module, "skill_registry", SkillRegistry(tmp_path))
    db = _session()
    identity = IdentityRepository().local(db)
    conversation = ConversationRepository().create(
        db, title="chat", channel="local", identity_id=identity.id
    )

    messages = with_agent_context(
        db,
        conversation,
        "请分析这个仓库",
        [{"role": "user", "content": "请分析这个仓库"}],
    )

    assert "research: 分析仓库结构" in messages[0]["content"]
    assert "不要提前注入的完整正文" not in messages[0]["content"]
    assert "read_skill" in build_tool_registry().names()
    db.close()
