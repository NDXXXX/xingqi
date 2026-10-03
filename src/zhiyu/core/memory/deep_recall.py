"""深度召回（Lane 2）：快速通道不足时，只读搜索情景记忆与历史消息。

只读、无模型调用、无副作用；失败或命中不足返回 None，继续用快速通道结果回答。
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiyu.infrastructure.database.models import ForgottenConversation
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository
from .retriever import _lexical_similarity, retrieve

_RECALL_RE = re.compile(r"上次|之前|以前|记得|说过|聊过|提到|那天|上回|上一次|回忆|当时")


def has_recall_intent(query: str) -> bool:
    return bool(_RECALL_RE.search(query))


def deep_recall(
    db: Session,
    identity_id: str,
    query: str,
    *,
    exclude_conversation_id: str | None = None,
) -> str | None:
    """返回可注入的历史片段；无命中返回 None。"""
    parts: list[str] = []
    episodic = MemoryRepository().list_owned(
        db, identity_id, tier="episodic", statuses=("active",)
    )
    hits = retrieve(query, episodic, top_k=3)
    if hits:
        parts.append("相关历史观察：\n" + "\n".join(f"- {item.content}" for item in hits))

    history = _search_history(db, identity_id, query, exclude_conversation_id=exclude_conversation_id)
    if history:
        parts.append(history)
    return "\n\n".join(parts) if parts else None


def _search_history(
    db: Session,
    identity_id: str,
    query: str,
    *,
    exclude_conversation_id: str | None,
    limit: int = 3,
) -> str | None:
    forgotten = set(
        db.scalars(select(ForgottenConversation.conversation_id))
    )
    conversations = [
        item
        for item in ConversationRepository().list(db)
        if item.identity_id == identity_id
        and item.id != exclude_conversation_id
        and item.id not in forgotten
    ]
    found: list[str] = []
    for conversation in conversations[:10]:
        for message in reversed(MessageRepository().list_by_conversation(db, conversation.id)):
            if message.role != "user":
                continue
            if query in message.content or _lexical_similarity(query, message.content) > 0.25:
                found.append(message.content[:200])
                if len(found) >= limit:
                    break
        if len(found) >= limit:
            break
    if found:
        return "用户过去说过：\n" + "\n".join(f"- {text}" for text in found)
    return None


def is_forgotten(db: Session, conversation_id: str) -> bool:
    return db.scalars(
        select(ForgottenConversation.id).where(
            ForgottenConversation.conversation_id == conversation_id
        )
    ).first() is not None
