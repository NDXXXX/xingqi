"""Agent 图 tool-calling 循环测试（用 fake provider，不碰网络/DB）。"""

from zhiyu.core.agent.runtime import run_agent, run_agent_stream
from zhiyu.core.providers.base import AIProvider, LLMResponse, ToolCall
from zhiyu.core.tools.registry import default_registry


class FakeProvider(AIProvider):
    """第一次请求工具，第二次返回最终答案。"""

    def __init__(self):
        self.calls = []

    async def chat(self, messages, tools=None, stream=False, **kwargs):
        self.calls.append(list(messages))
        has_tool = any(m.get("role") == "tool" for m in messages)
        if not has_tool:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call_1", name="calculator", arguments={"expression": "2 + 3"})],
            )
        tool_content = next(m["content"] for m in messages if m.get("role") == "tool")
        return LLMResponse(content=f"结果是 {tool_content}", tool_calls=[])


class PlainProvider(AIProvider):
    def __init__(self):
        pass

    async def chat(self, messages, tools=None, stream=False, **kwargs):
        return LLMResponse(content="直接回答", tool_calls=[])


async def _collect(provider, messages):
    steps = []
    final = None
    async for event in run_agent(provider, default_registry(), "test-model", "conv-1", messages):
        if event["type"] == "step":
            steps.append(event["name"])
        elif event["type"] == "final":
            final = event["final_response"]
    return steps, final


async def test_tool_loop_runs_calculator():
    provider = FakeProvider()
    steps, final = await _collect(provider, [{"role": "user", "content": "计算 2+3"}])
    assert final == "结果是 5"
    assert "execute_tool" in steps
    assert steps.count("call_llm") == 2
    assert len(provider.calls) == 2


async def test_plain_answer_skips_tools():
    steps, final = await _collect(PlainProvider(), [{"role": "user", "content": "你好"}])
    assert final == "直接回答"
    assert "execute_tool" not in steps
    assert steps.count("call_llm") == 1
    assert steps == ["load_context", "call_llm", "finalize"]


class StreamingProvider(PlainProvider):
    async def stream_chat(self, messages, tools=None, **kwargs):
        yield "直接"
        yield "回答"
        yield LLMResponse(content="直接回答", tool_calls=[])


async def test_streaming_agent_forwards_provider_chunks():
    events = []
    async for event in run_agent_stream(
        StreamingProvider(), default_registry(), "test-model", "conv-1", [{"role": "user", "content": "你好"}]
    ):
        events.append(event)

    assert [event["text"] for event in events if event["type"] == "chunk"] == ["直接", "回答"]
    assert events[-1] == {"type": "final", "final_response": "直接回答"}


async def test_streaming_agent_fallback_keeps_tool_loop():
    events = []
    async for event in run_agent_stream(
        FakeProvider(), default_registry(), "test-model", "conv-1", [{"role": "user", "content": "计算 2+3"}]
    ):
        events.append(event)

    assert any(event.get("name") == "execute_tool" for event in events)
    assert events[-1]["final_response"] == "结果是 5"
