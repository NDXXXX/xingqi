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
from .retriever import _lexical_similarity, build_query_plan, retrieve

_RECALL_RE = re.compile(r"上次|之前|以前|记得|说过|聊过|提到|那天|上回|上一次|回忆|当时")


def has_recall_intent(query: str) -> bool:
    return bool(_RECALL_RE.search(query))


def deep_recall(
    db: Session,
    identity_id: str,
    query: str,
    *,
    exclude_conversation_id: str | None = None,
    current_conversation_id: str | None = None,
) -> str | None:
    """返回可注入的历史片段；无命中返回 None。"""
    parts: list[str] = []
    episodic = MemoryRepository().list_owned(
        db, identity_id, tier="episodic", statuses=("active",)
    )
    episodic = [
        item for item in episodic if item.promotion_status not in {"promoted", "rejected", "deferred"}
    ]
    hits = retrieve(query, episodic, top_k=3)
    if hits:
        parts.append("相关历史观察：\n" + "\n".join(f"- {item.content}" for item in hits))

    history = _search_history(
        db,
        identity_id,
        query,
        exclude_conversation_id=exclude_conversation_id,
        current_conversation_id=current_conversation_id,
    )
    if history:
        parts.append(history)
    return "\n\n".join(parts) if parts else None


def _search_history(
    db: Session,
    identity_id: str,
    query: str,
    *,
    exclude_conversation_id: str | None,
    current_conversation_id: str | None = None,
    limit: int = 3,
) -> str | None:
    forgotten = set(
        db.scalars(
            select(ForgottenConversation.conversation_id).where(
                ForgottenConversation.identity_id == identity_id
            )
        )
    )
    conversations = [
        item
        for item in ConversationRepository().list(db)
        if item.identity_id == identity_id
        and item.id != exclude_conversation_id
        and (current_conversation_id is None or item.id == current_conversation_id)
        and item.id not in forgotten
    ]
    plan = build_query_plan(query)
    found: list[tuple[float, str]] = []
    for conversation in conversations[:10]:
        messages = MessageRepository().list_by_conversation(db, conversation.id)
        searchable_end = len(messages)
        if conversation.id == current_conversation_id:
            # 最近消息已在常规上下文里，只搜索可能被窗口裁掉的较早部分。
            searchable_end = max(0, len(messages) - 8)
        for index in range(searchable_end - 1, -1, -1):
            message = messages[index]
            if message.role != "user":
                continue
            score = max(
                (_lexical_similarity(variant, message.content) for variant in plan.variants),
                default=0.0,
            )
            if query not in message.content and score <= 0.25:
                continue
            window = messages[max(0, index - 1) : min(len(messages), index + 2)]
            excerpt = "\n".join(
                f"  {item.role}: {item.content[:200]}" for item in window
            )
            date = message.created_at.strftime("%Y-%m-%d")
            found.append((score, f"- [{date} 历史会话]\n{excerpt}"))
    found.sort(key=lambda item: item[0], reverse=True)
    if found:
        return "用户过去说过（含命中前后文）：\n" + "\n".join(
            text for _, text in found[:limit]
        )
    return None


def is_forgotten(
    db: Session, conversation_id: str, identity_id: str | None = None
) -> bool:
    query = select(ForgottenConversation.id).where(
        ForgottenConversation.conversation_id == conversation_id
    )
    if identity_id is not None:
        query = query.where(ForgottenConversation.identity_id == identity_id)
    return db.scalars(query).first() is not None
