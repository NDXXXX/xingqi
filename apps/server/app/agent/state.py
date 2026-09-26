"""Agent 状态（对齐设计文档 §16）。"""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    conversation_id: str | None
    user_id: str | None
    character_id: str | None
    messages: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    skills: list[str]
    tools: list[str]
    tool_results: list[dict[str, Any]]
    final_response: str | None
    # 内部运行时状态
    pending_tool_calls: list[Any]
    round: int
