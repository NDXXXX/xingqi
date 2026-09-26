"""统一 Agent 执行核心：非流式与流式入口消费同一事件序列。"""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from ..providers.base import AIProvider, LLMResponse
from ..tools.registry import ToolRegistry
from .graph import MAX_ROUNDS

RUN_TIMEOUT_SECONDS = 180


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if any(word in key.lower() for word in ("token", "key", "password", "secret")) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _redact_output(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return _redact(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return value
    return _redact(value)


async def _execute(
    provider: AIProvider,
    registry: ToolRegistry,
    model: str,
    messages: list[dict[str, Any]],
    *,
    streaming: bool,
) -> AsyncGenerator[dict[str, Any], None]:
    current_messages = list(messages)
    tools = registry.to_openai_tools()
    final_response = ""

    yield {"type": "step", "name": "load_context", "status": "completed"}
    for round_number in range(1, MAX_ROUNDS + 1):
        response: LLMResponse | None = None
        emitted_content = False

        if streaming:
            async for item in provider.stream_chat(messages=current_messages, tools=tools, model=model):
                if isinstance(item, str):
                    emitted_content = True
                    yield {"type": "chunk", "text": item}
                else:
                    response = item
        else:
            result = await provider.chat(messages=current_messages, tools=tools, model=model, stream=False)
            if not isinstance(result, LLMResponse):
                raise TypeError("stream=False 必须返回 LLMResponse")
            response = result

        if response is None:
            raise RuntimeError("Provider 流结束但未返回最终状态")

        yield {"type": "step", "name": "call_llm", "status": "completed"}
        assistant: dict[str, Any] = {"role": "assistant", "content": response.content or ""}
        if response.tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in response.tool_calls
            ]
        current_messages.append(assistant)

        if response.tool_calls and round_number < MAX_ROUNDS:
            for call in response.tool_calls:
                tool = registry.get(call.name)
                error: str | None = None
                audit_output: Any
                if tool is None:
                    error = f"未知工具: {call.name}"
                    content = json.dumps({"error": error}, ensure_ascii=False)
                    audit_output = {"error": error}
                else:
                    try:
                        output = await asyncio.wait_for(
                            tool.execute(**call.arguments),
                            timeout=tool.timeout_seconds,
                        )
                        content = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
                        audit_output = _redact_output(output)
                    except Exception as exc:
                        error = str(exc)
                        content = json.dumps({"error": error}, ensure_ascii=False)
                        audit_output = {"error": error}
                current_messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
                yield {
                    "type": "tool",
                    "name": call.name,
                    "status": "failed" if error else "completed",
                    "input": _redact(call.arguments),
                    "output": audit_output,
                    "error": error,
                }
            yield {"type": "step", "name": "execute_tool", "status": "completed"}
            continue

        final_response = response.content or ""
        if streaming and final_response and not emitted_content:
            yield {"type": "chunk", "text": final_response}
        break

    yield {"type": "step", "name": "finalize", "status": "completed"}
    yield {"type": "final", "final_response": final_response}


async def run_agent(
    provider: AIProvider,
    registry: ToolRegistry,
    model: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
) -> AsyncGenerator[dict[str, Any], None]:
    del conversation_id
    async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
        async for event in _execute(provider, registry, model, messages, streaming=False):
            yield event


async def run_agent_stream(
    provider: AIProvider,
    registry: ToolRegistry,
    model: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
) -> AsyncGenerator[dict[str, Any], None]:
    del conversation_id
    async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
        async for event in _execute(provider, registry, model, messages, streaming=True):
            yield event
