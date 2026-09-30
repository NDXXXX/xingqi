"""Provider 消息转换与原生流解析测试。"""

import zhiyu.core.providers.openai_compatible as openai_module
from zhiyu.core.providers.anthropic import AnthropicProvider
from zhiyu.core.providers.base import LLMResponse
from zhiyu.core.providers.openai_compatible import OpenAICompatibleProvider


def test_anthropic_converts_system_and_tools():
    system, messages = AnthropicProvider._payload_messages(
        [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "计算"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "function": {"name": "calculator", "arguments": '{"expression":"2+3"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "5"},
        ]
    )
    tools = AnthropicProvider._payload_tools(
        [{
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "计算",
                "parameters": {"type": "object", "properties": {}},
            },
        }]
    )

    assert system == "你是助手"
    assert messages[1]["content"][0]["type"] == "tool_use"
    assert messages[2]["content"][0]["type"] == "tool_result"
    assert tools == [{
        "name": "calculator",
        "description": "计算",
        "input_schema": {"type": "object", "properties": {}},
    }]


async def test_openai_stream_assembles_text_and_tool_calls(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"先"}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"calculator","arguments":"{\\"expression\\":"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"2+3\\"}"}}]}}]}',
        "data: [DONE]",
    ]

    class FakeResponse:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            for line in lines:
                yield line

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *_args):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return FakeStreamContext()

    monkeypatch.setattr(openai_module.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    provider = OpenAICompatibleProvider(api_key="key", base_url="https://example.test")
    events = [event async for event in provider._stream({}, {"model": "test", "stream": True})]

    assert events[0] == "先"
    assert isinstance(events[-1], LLMResponse)
    assert events[-1].content == "先"
    assert events[-1].tool_calls[0].name == "calculator"
    assert events[-1].tool_calls[0].arguments == {"expression": "2+3"}
