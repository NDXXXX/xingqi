"""LangGraph 单 Agent 图：load_context → call_llm ⇄ execute_tool → finalize。

图保持 pure（不碰 DB、不 import 具体 provider），provider / registry / model
通过闭包注入，便于用 fake provider 单测。
"""

import json

from langgraph.graph import END, START, StateGraph

from zhiyu.core.providers.base import AIProvider
from zhiyu.core.tools.registry import ToolRegistry
from .state import AgentState

MAX_ROUNDS = 10


def build_agent_graph(
    provider: AIProvider,
    registry: ToolRegistry,
    model: str,
):
    tools = registry.to_openai_tools()

    def load_context(state: AgentState) -> dict:
        # 上下文由入口统一注入；保留节点用于运行轨迹展示。
        return {}

    async def call_llm(state: AgentState) -> dict:
        resp = await provider.chat(
            messages=state["messages"], tools=tools, model=model, stream=False
        )
        assistant: dict = {"role": "assistant", "content": resp.content or ""}
        if resp.tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                }
                for tc in resp.tool_calls
            ]
        return {
            "messages": state["messages"] + [assistant],
            "pending_tool_calls": resp.tool_calls,
            "final_response": resp.content if not resp.tool_calls else None,
            "round": state.get("round", 0) + 1,
        }

    async def execute_tool(state: AgentState) -> dict:
        appended: list[dict] = []
        results: list[dict] = []
        for tc in state.get("pending_tool_calls", []):
            tool = registry.get(tc.name)
            if tool is None:
                content = json.dumps({"error": f"未知工具: {tc.name}"}, ensure_ascii=False)
            else:
                try:
                    output = await tool.execute(**tc.arguments)
                    content = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
                except Exception as e:  # 工具异常回填给模型，而非中断图
                    content = json.dumps({"error": str(e)}, ensure_ascii=False)
            appended.append({"role": "tool", "tool_call_id": tc.id, "content": content})
            results.append({"name": tc.name, "content": content})
        return {
            "messages": state["messages"] + appended,
            "tool_results": state.get("tool_results", []) + results,
            "pending_tool_calls": [],
        }

    def route_tools(state: AgentState) -> str:
        if state.get("pending_tool_calls") and state.get("round", 0) < MAX_ROUNDS:
            return "execute_tool"
        return "finalize"

    def finalize(state: AgentState) -> dict:
        return {"final_response": state.get("final_response") or ""}

    builder = StateGraph(AgentState)
    builder.add_node("load_context", load_context)
    builder.add_node("call_llm", call_llm)
    builder.add_node("execute_tool", execute_tool)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "call_llm")
    builder.add_conditional_edges(
        "call_llm", route_tools, {"execute_tool": "execute_tool", "finalize": "finalize"}
    )
    builder.add_edge("execute_tool", "call_llm")
    builder.add_edge("finalize", END)

    return builder.compile()
