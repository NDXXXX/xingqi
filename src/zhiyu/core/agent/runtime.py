"""统一 Agent 执行核心：非流式与流式入口消费同一事件序列。"""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.core.tools.registry import ToolRegistry
from .graph import MAX_ROUNDS

RUN_TIMEOUT_SECONDS = 180
ProviderFallback = tuple[str, AIProvider, str]


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


def _retryable_provider_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


async def _execute(
    provider: AIProvider,
    registry: ToolRegistry,
    model: str,
    messages: list[dict[str, Any]],
    *,
    streaming: bool,
    emit_content: bool = False,
    supports_tools: bool = True,
    max_output_tokens: int | None = None,
    provider_id: str | None = None,
    fallbacks: list[ProviderFallback] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    current_messages = list(messages)
    tools = registry.to_openai_tools() if supports_tools else None
    candidates: list[ProviderFallback] = [
        (provider_id or "primary", provider, model),
        *(fallbacks or []),
    ]
    active_candidate = 0
    final_response = ""
    prompt_tokens = 0
    completion_tokens = 0
    has_usage = False

    yield {"type": "step", "name": "load_context", "status": "completed"}
    for round_number in range(1, MAX_ROUNDS + 1):
        response: LLMResponse | None = None
        emitted_content = False
        call_succeeded = False
        last_error: Exception | None = None

        for candidate_index in range(active_candidate, len(candidates)):
            candidate_id, candidate_provider, candidate_model = candidates[candidate_index]
            provider_options: dict[str, Any] = {"model": candidate_model}
            if max_output_tokens is not None:
                provider_options["max_output_tokens"] = max_output_tokens
            for attempt in range(2):
                response = None
                emitted_content = False
                try:
                    if streaming:
                        async for item in candidate_provider.stream_chat(
                            messages=current_messages,
                            tools=tools,
                            **provider_options,
                        ):
                            if isinstance(item, str):
                                emitted_content = True
                                yield {"type": "chunk", "text": item}
                            else:
                                response = item
                    else:
                        result = await candidate_provider.chat(
                            messages=current_messages,
                            tools=tools,
                            stream=False,
                            **provider_options,
                        )
                        if not isinstance(result, LLMResponse):
                            raise TypeError("stream=False 必须返回 LLMResponse")
                        response = result
                except Exception as exc:
                    last_error = exc
                    if emitted_content or not _retryable_provider_error(exc):
                        raise
                    if attempt == 0:
                        yield {
                            "type": "step",
                            "name": "provider_retry",
                            "status": "completed",
                            "output": {"provider_id": candidate_id, "model": candidate_model},
                        }
                        await asyncio.sleep(0)
                        continue
                    break
                else:
                    active_candidate = candidate_index
                    call_succeeded = True
                    break
            if call_succeeded:
                break
            if candidate_index + 1 < len(candidates):
                next_id, _, next_model = candidates[candidate_index + 1]
                yield {
                    "type": "step",
                    "name": "provider_fallback",
                    "status": "completed",
                    "output": {
                        "from_provider_id": candidate_id,
                        "to_provider_id": next_id,
                        "model": next_model,
                        "reason": str(last_error) if last_error else "provider unavailable",
                    },
                }

        if not call_succeeded:
            if last_error is not None:
                raise last_error
            raise RuntimeError("没有可用的 Provider")

        if response is None:
            raise RuntimeError("Provider 流结束但未返回最终状态")

        if response.prompt_tokens is not None:
            prompt_tokens += response.prompt_tokens
            has_usage = True
        if response.completion_tokens is not None:
            completion_tokens += response.completion_tokens
            has_usage = True

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

        if supports_tools and response.tool_calls and round_number < MAX_ROUNDS:
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

        if response.tool_calls and round_number >= MAX_ROUNDS:
            final_response = response.content or "已达到工具调用轮次上限，请缩小任务范围后重试。"
            if emit_content and final_response and not emitted_content:
                yield {"type": "chunk", "text": final_response}
            break

        final_response = response.content or ""
        if emit_content and final_response and not emitted_content:
            yield {"type": "chunk", "text": final_response}
        break

    yield {"type": "step", "name": "finalize", "status": "completed"}
    yield {
        "type": "final",
        "final_response": final_response,
        "prompt_tokens": prompt_tokens if has_usage else None,
        "completion_tokens": completion_tokens if has_usage else None,
        "provider_id": candidates[active_candidate][0],
        "model": candidates[active_candidate][2],
    }


async def run_agent(
    provider: AIProvider,
    registry: ToolRegistry,
    model: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
    *,
    supports_tools: bool = True,
    max_output_tokens: int | None = None,
    provider_id: str | None = None,
    fallbacks: list[ProviderFallback] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    del conversation_id
    async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
        async for event in _execute(
            provider,
            registry,
            model,
            messages,
            streaming=False,
            supports_tools=supports_tools,
            max_output_tokens=max_output_tokens,
            provider_id=provider_id,
            fallbacks=fallbacks,
        ):
            yield event


async def run_agent_stream(
    provider: AIProvider,
    registry: ToolRegistry,
    model: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
    *,
    supports_streaming: bool = True,
    supports_tools: bool = True,
    max_output_tokens: int | None = None,
    provider_id: str | None = None,
    fallbacks: list[ProviderFallback] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    del conversation_id
    async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
        async for event in _execute(
            provider,
            registry,
            model,
            messages,
            streaming=supports_streaming,
            emit_content=True,
            supports_tools=supports_tools,
            max_output_tokens=max_output_tokens,
            provider_id=provider_id,
            fallbacks=fallbacks,
        ):
            yield event
