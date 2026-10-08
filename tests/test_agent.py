"""Agent 图 tool-calling 循环测试（用 fake provider，不碰网络/DB）。"""

import asyncio

import httpx

from zhiyu.core.agent.runtime import ProviderCandidate, run_agent, run_agent_stream
from zhiyu.core.agent.run_manager import ActiveRunManager
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


async def test_active_run_manager_cancels_only_matching_conversation():
    manager = ActiveRunManager()
    started = {"one": asyncio.Event(), "two": asyncio.Event()}
    cancelled = {"one": asyncio.Event(), "two": asyncio.Event()}

    async def running(run_id, conversation_id):
        manager.register(run_id, conversation_id)
        started[conversation_id].set()
        try:
            await asyncio.Future()
        finally:
            cancelled[conversation_id].set()
            manager.unregister(run_id)

    one = asyncio.create_task(running("run-1", "one"))
    two = asyncio.create_task(running("run-2", "two"))
    await asyncio.gather(started["one"].wait(), started["two"].wait())

    assert manager.cancel_conversation("one") is True
    assert manager.cancel_conversation("missing") is False
    await asyncio.wait_for(cancelled["one"].wait(), 1)
    assert cancelled["two"].is_set() is False
    two.cancel()
    await asyncio.gather(one, two, return_exceptions=True)


async def test_active_run_manager_cancels_matching_external_channel_session():
    manager = ActiveRunManager()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def running():
        manager.register(
            "qq-run",
            "internal-conversation",
            ("qq", "config-1", "group", "group-7"),
        )
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()
            manager.unregister("qq-run")

    task = asyncio.create_task(running())
    await started.wait()
    assert manager.cancel_channel_session("qq", "config-1", "private", "user-1") is False
    assert manager.cancel_channel_session("qq", "config-1", "group", "group-7") is True
    await asyncio.wait_for(cancelled.wait(), 1)
    await asyncio.gather(task, return_exceptions=True)


async def test_streaming_agent_forwards_provider_chunks():
    events = []
    async for event in run_agent_stream(
        StreamingProvider(), default_registry(), "test-model", "conv-1", [{"role": "user", "content": "你好"}]
    ):
        events.append(event)

    assert [event["text"] for event in events if event["type"] == "chunk"] == ["直接", "回答"]
    assert events[-1]["type"] == "final"
    assert events[-1]["final_response"] == "直接回答"
    assert events[-1]["provider_id"] == "primary"


async def test_retryable_primary_failure_switches_to_fallback_and_records_usage():
    class UnavailableProvider(PlainProvider):
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools=None, stream=False, **kwargs):
            self.calls += 1
            request = httpx.Request("POST", "https://primary.invalid")
            raise httpx.ConnectError("offline", request=request)

    class FallbackProvider(PlainProvider):
        async def chat(self, messages, tools=None, stream=False, **kwargs):
            return LLMResponse(
                content="备用模型回答",
                prompt_tokens=12,
                completion_tokens=4,
            )

    primary = UnavailableProvider()
    events = [
        event
        async for event in run_agent(
            primary,
            default_registry(),
            "primary-model",
            "conv-1",
            [{"role": "user", "content": "你好"}],
            provider_id="primary",
            fallbacks=[
                ProviderCandidate("backup", FallbackProvider(), "backup-model")
            ],
        )
    ]

    assert primary.calls == 2
    assert any(event.get("name") == "provider_retry" for event in events)
    assert any(event.get("name") == "provider_fallback" for event in events)
    assert events[-1]["final_response"] == "备用模型回答"
    assert events[-1]["provider_id"] == "backup"
    assert events[-1]["model"] == "backup-model"
    assert events[-1]["prompt_tokens"] == 12
    assert events[-1]["completion_tokens"] == 4


async def test_fallback_uses_its_model_capabilities_and_context_window():
    class UnavailableProvider(PlainProvider):
        async def chat(self, messages, tools=None, stream=False, **kwargs):
            request = httpx.Request("POST", "https://primary.invalid")
            raise httpx.ConnectError("offline", request=request)

    class FallbackProvider(PlainProvider):
        def __init__(self):
            self.request = None

        async def chat(self, messages, tools=None, stream=False, **kwargs):
            self.request = {"messages": messages, "tools": tools, "stream": stream, **kwargs}
            return LLMResponse(content="备用模型回答")

    fallback = FallbackProvider()
    messages = [
        {"role": role, "content": f"{role} 内容 " * 200}
        for role in ("user", "assistant", "user", "assistant")
    ]
    messages.append({"role": "user", "content": "保留最新请求"})

    events = [
        event
        async for event in run_agent_stream(
            UnavailableProvider(),
            default_registry(),
            "primary-model",
            "conv-1",
            messages,
            fallbacks=[
                ProviderCandidate(
                    "backup",
                    fallback,
                    "backup-model",
                    supports_tools=False,
                    supports_streaming=False,
                    context_window=200,
                    max_output_tokens=64,
                )
            ],
        )
    ]

    assert events[-1]["final_response"] == "备用模型回答"
    assert fallback.request is not None
    assert fallback.request["tools"] is None
    assert fallback.request["stream"] is False
    assert fallback.request["model"] == "backup-model"
    assert fallback.request["max_output_tokens"] == 64
    assert fallback.request["messages"][-1]["content"] == "保留最新请求"
    assert len(fallback.request["messages"]) < len(messages)


async def test_streaming_agent_fallback_keeps_tool_loop():
    events = []
    async for event in run_agent_stream(
        FakeProvider(), default_registry(), "test-model", "conv-1", [{"role": "user", "content": "计算 2+3"}]
    ):
        events.append(event)

    assert any(event.get("name") == "execute_tool" for event in events)
    assert events[-1]["final_response"] == "结果是 5"


class CapabilityProvider(AIProvider):
    def __init__(self):
        super().__init__("fake-key")
        self.requests = []

    async def chat(self, messages, tools=None, stream=False, **kwargs):
        self.requests.append({"tools": tools, "stream": stream, **kwargs})
        return LLMResponse(content="完整回答")


async def test_streaming_ui_falls_back_for_non_streaming_model_and_honors_limits():
    provider = CapabilityProvider()
    events = [
        event
        async for event in run_agent_stream(
            provider,
            default_registry(),
            "test-model",
            "conv-1",
            [{"role": "user", "content": "你好"}],
            supports_streaming=False,
            supports_tools=False,
            max_output_tokens=321,
        )
    ]

    assert [event["text"] for event in events if event["type"] == "chunk"] == ["完整回答"]
    assert provider.requests == [{
        "tools": None,
        "stream": False,
        "model": "test-model",
        "max_output_tokens": 321,
    }]
