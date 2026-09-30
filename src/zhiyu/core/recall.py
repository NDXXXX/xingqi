"""会话续接与恢复：默认续接最近会话 + 未完成事项。"""

from sqlalchemy.orm import Session

from zhiyu.infrastructure.database.models import Conversation
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository


def last_local_conversation(
    db: Session, *, exclude_conversation_id: str | None = None
) -> Conversation | None:
    """最近一条有消息的本地会话，作为默认续接对象。"""
    conversations = ConversationRepository()
    messages = MessageRepository()
    for conv in conversations.list(db):
        if conv.channel != "local" or conv.id == exclude_conversation_id:
            continue
        if messages.list_by_conversation(db, conv.id):
            return conv
    return None


def list_goals(db: Session, identity_id: str | None) -> list[str]:
    """进行中的目标/项目（goal/project 记忆）。"""
    return [
        m.content
        for m in MemoryRepository().list(db, identity_id)
        if m.type in ("goal", "project")
    ]


def build_recall(
    db: Session,
    identity_id: str | None,
    *,
    exclude_conversation_id: str | None = None,
) -> str | None:
    """生成 fresh 会话首 turn 的续作上下文；无内容返回 None。"""
    last = last_local_conversation(db, exclude_conversation_id=exclude_conversation_id)
    goals = list_goals(db, identity_id)

    parts: list[str] = []
    if last is not None:
        msgs = MessageRepository().list_by_conversation(db, last.id)
        tail = [f"{'你' if m.role == 'user' else '助手'}: {m.content}" for m in msgs[-6:]]
        parts.append(f"上次会话「{last.title}」末尾：\n" + "\n".join(tail))
    if goals:
        parts.append("用户进行中的目标/项目：" + "；".join(goals))

    return "\n\n".join(parts) if parts else None


def format_welcome(continuing_title: str | None, goals: list[str]) -> str | None:
    """生成开场欢迎文本；无续接也无事项时返回 None。"""
    lines: list[str] = []
    if continuing_title:
        lines.append(f"已继续上次对话「{continuing_title}」")
    elif goals:
        lines.append("你好，你有一些进行中的事项。想继续的话：")
    if goals:
        for index, goal in enumerate(goals, 1):
            lines.append(f"  {index}. 跟进：{goal}")
        lines.append("（输入数字跟进，或直接说话）")
    return "\n".join(lines) if lines else None
