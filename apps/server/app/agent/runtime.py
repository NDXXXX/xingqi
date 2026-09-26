"""Agent 运行入口：组装 state、跑图、产出步骤事件与最终回答。"""

from collections.abc import AsyncGenerator
from typing import Any

from ..providers.base import AIProvider
from ..tools.registry import ToolRegistry
from .graph import build_agent_graph
from .state import AgentState


async def run_agent(
    provider: AIProvider,
    registry: ToolRegistry,
    model: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
) -> AsyncGenerator[dict[str, Any], None]:
    """运行一次 Agent。

    依次 yield：
      {"type": "step", "name": <node>, "status": "done"}  每个节点完成时
      {"type": "final", "final_response": <str>}           最终回答
    """
    graph = build_agent_graph(provider, registry, model)
    state: AgentState = {
        "conversation_id": conversation_id,
        "user_id": None,
        "character_id": None,
        "messages": messages,
        "memories": [],
        "skills": [],
        "tools": registry.names(),
        "tool_results": [],
        "final_response": None,
        "pending_tool_calls": [],
        "round": 0,
    }
    final_response = ""
    async for update in graph.astream(state, stream_mode="updates"):
        for node, value in update.items():
            yield {"type": "step", "name": node, "status": "done"}
            if node == "finalize":
                final_response = (value or {}).get("final_response") or ""
    yield {"type": "final", "final_response": final_response}
