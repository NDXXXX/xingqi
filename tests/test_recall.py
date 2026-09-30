"""会话续接与恢复（recall）测试。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.core.agent.context import with_agent_context
from zhiyu.core.recall import (
    build_recall,
    format_welcome,
    last_local_conversation,
    list_goals,
)
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _conversation_with_messages(db, title="旧会话", n=2):
    conv = ConversationRepository().create(db, title=title, channel="local")
    for i in range(n):
        MessageRepository().create(db, conversation_id=conv.id, role="user", content=f"问题{i}")
        MessageRepository().create(db, conversation_id=conv.id, role="assistant", content=f"回答{i}")
    return conv


def test_build_recall_none_when_no_history():
    db = _session()
    assert build_recall(db, None) is None
    db.close()


def test_build_recall_includes_last_conversation_tail():
    db = _session()
    _conversation_with_messages(db)

    context = build_recall(db, None)

    assert context is not None
    assert "旧会话" in context
    assert "问题1" in context
    db.close()


def test_build_recall_excludes_current_conversation():
    db = _session()
    current = _conversation_with_messages(db, title="当前会话")
    _conversation_with_messages(db, title="上一次会话")

    context = build_recall(db, None, exclude_conversation_id=current.id)

    assert context is not None
    assert "上一次会话" in context
    assert "当前会话" not in context
    db.close()


def test_build_recall_includes_goals():
    db = _session()
    MemoryRepository().create(db, type="goal", content="完成 MCP 接入")

    context = build_recall(db, None)

    assert context is not None
    assert "完成 MCP 接入" in context
    db.close()


def test_last_local_conversation_skips_empty():
    db = _session()
    ConversationRepository().create(db, title="空会话", channel="local")

    assert last_local_conversation(db) is None
    db.close()


def test_last_local_conversation_returns_most_recent():
    db = _session()
    _conversation_with_messages(db, title="旧")
    _conversation_with_messages(db, title="新")

    assert last_local_conversation(db).title == "新"
    db.close()


def test_list_goals_filters_types():
    db = _session()
    MemoryRepository().create(db, type="goal", content="目标A")
    MemoryRepository().create(db, type="project", content="项目B")
    MemoryRepository().create(db, type="fact", content="事实C")

    assert set(list_goals(db, None)) == {"目标A", "项目B"}
    db.close()


def test_format_welcome_continuing():
    assert format_welcome("旧会话", []) == "已继续上次对话「旧会话」"


def test_format_welcome_goals_only():
    welcome = format_welcome(None, ["完成 MCP 接入"])

    assert "1. 跟进：完成 MCP 接入" in welcome


def test_format_welcome_none_when_empty():
    assert format_welcome(None, []) is None


def test_with_agent_context_injects_recall():
    db = _session()
    conv = ConversationRepository().create(db, title="chat", channel="local")

    messages = with_agent_context(
        db,
        conv,
        "继续",
        [{"role": "user", "content": "继续"}],
        recall="上次会话末尾：xxx",
    )

    assert messages[0]["role"] == "system"
    assert "上次会话末尾：xxx" in messages[0]["content"]
    db.close()
