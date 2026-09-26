"""共享的 Agent 上下文与工具组装。"""

import json

from sqlalchemy.orm import Session

from ..characters.prompts import build_system_prompt
from ..database.models import Conversation
from ..database.repositories.character_repository import CharacterRepository
from ..database.repositories.memory_repository import MemoryRepository
from ..memory.retriever import retrieve
from ..mcp.manager import default_manager as mcp_manager
from ..skills.registry import default_registry as skill_registry
from ..tools.registry import ToolRegistry, default_registry

character_repo = CharacterRepository()
memory_repo = MemoryRepository()


def with_agent_context(
    db: Session,
    conversation: Conversation,
    query: str,
    messages: list[dict],
    context_window: int | None = None,
    max_output_tokens: int | None = None,
) -> list[dict]:
    """把角色、相关记忆和匹配到的 Skill 注入消息列表。"""
    system_parts: list[str] = []
    if conversation.character_id:
        character = character_repo.get(db, conversation.character_id)
        if character is not None:
            system_parts.append(build_system_prompt(character))

    relevant = retrieve(query, memory_repo.list(db, conversation.identity_id))
    if relevant:
        system_parts.append("相关记忆：\n" + "\n".join(f"- {m.content}" for m in relevant))

    matched = skill_registry.match(query)
    if matched:
        system_parts.append(
            "可用技能：\n" + "\n\n".join(f"技能：{skill.name}\n{skill.content}" for skill in matched)
        )

    contextualized = messages
    if system_parts:
        contextualized = [
            {"role": "system", "content": "\n\n".join(system_parts)},
            *messages,
        ]
    return trim_messages(contextualized, context_window, max_output_tokens)


def trim_messages(
    messages: list[dict],
    context_window: int | None,
    max_output_tokens: int | None = None,
) -> list[dict]:
    """按模型窗口保留全部 system context 与尽可能新的会话消息。"""
    if not context_window:
        return messages
    system_messages = [message for message in messages if message.get("role") == "system"]
    history = [message for message in messages if message.get("role") != "system"]
    budget_chars = max(0, (context_window - (max_output_tokens or 1024) - 256) * 4)
    system_chars = sum(len(json.dumps(message, ensure_ascii=False)) for message in system_messages)
    remaining = max(0, budget_chars - system_chars)
    selected: list[dict] = []
    for message in reversed(history):
        size = len(json.dumps(message, ensure_ascii=False))
        if selected and size > remaining:
            break
        selected.append(message)
        remaining = max(0, remaining - size)
    selected.reverse()
    while selected and selected[0].get("role") == "tool":
        selected.pop(0)
    return [*system_messages, *selected]


def build_tool_registry() -> ToolRegistry:
    """合并内置工具与当前已连接 MCP 服务器提供的工具。"""
    registry = default_registry()
    for tool in mcp_manager.tools():
        registry.register(tool)
    return registry
