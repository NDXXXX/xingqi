"""Anthropic Provider（Messages API）。"""

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from .base import AIProvider, LLMResponse, ToolCall


class AnthropicProvider(AIProvider):
    @staticmethod
    def _payload_messages(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role == "system":
                system_parts.append(str(message.get("content") or ""))
                continue
            if role == "tool":
                item = {
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": message.get("tool_call_id", ""),
                        "content": str(message.get("content") or ""),
                    }],
                }
            elif role == "assistant" and message.get("tool_calls"):
                content: list[dict[str, Any]] = []
                if message.get("content"):
                    content.append({"type": "text", "text": message["content"]})
                for call in message["tool_calls"]:
                    fn = call.get("function") or {}
                    try:
                        arguments = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                    content.append({
                        "type": "tool_use",
                        "id": call.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": arguments,
                    })
                item = {"role": "assistant", "content": content}
            else:
                item = {"role": role, "content": message.get("content") or ""}

            if converted and converted[-1]["role"] == item["role"] == "user":
                previous = converted[-1]["content"]
                current = item["content"]
                previous_blocks = previous if isinstance(previous, list) else [{"type": "text", "text": previous}]
                current_blocks = current if isinstance(current, list) else [{"type": "text", "text": current}]
                converted[-1]["content"] = [*previous_blocks, *current_blocks]
            else:
                converted.append(item)
        return "\n\n".join(system_parts) or None, converted

    @staticmethod
    def _payload_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "input_schema": tool["function"].get("parameters", {"type": "object", "properties": {}}),
            }
            for tool in tools
        ]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs,
    ) -> str | AsyncGenerator[str, None]:
        model = kwargs.get("model")
        if not model:
            raise ValueError("缺少 model")
        system, converted_messages = self._payload_messages(messages)
        payload: dict[str, Any] = {"model": model, "messages": converted_messages, "max_tokens": 1024, "stream": stream}
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]
        if system:
            payload["system"] = system
        converted_tools = self._payload_tools(tools)
        if converted_tools:
            payload["tools"] = converted_tools
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        if not stream:
            async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
                resp = await client.post(f"{self.base_url}/v1/messages", headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            return self._parse_completion(data)

        return self._stream(headers, payload)

    @staticmethod
    def _parse_completion(data: dict[str, Any]) -> LLMResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.get("id", ""), name=block.get("name", ""), arguments=block.get("input") or {})
                )
        return LLMResponse(content="".join(content_parts), tool_calls=tool_calls)

    async def _stream(
        self, headers: dict[str, str], payload: dict[str, Any]
    ) -> AsyncGenerator[str | LLMResponse, None]:
        content_parts: list[str] = []
        pending_calls: dict[int, dict[str, str]] = {}
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            async with client.stream(
                "POST", f"{self.base_url}/v1/messages", headers=headers, json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = json.loads(line[5:].strip())
                    event_type = data.get("type")
                    if event_type == "content_block_start":
                        block = data.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            pending_calls[data.get("index", 0)] = {
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "arguments": "",
                            }
                    elif event_type == "content_block_delta":
                        delta = data.get("delta") or {}
                        text = delta.get("text", "")
                        if text:
                            content_parts.append(text)
                            yield text
                        partial_json = delta.get("partial_json")
                        if partial_json is not None:
                            call = pending_calls.setdefault(
                                data.get("index", 0), {"id": "", "name": "", "arguments": ""}
                            )
                            call["arguments"] += partial_json

        tool_calls: list[ToolCall] = []
        for call in pending_calls.values():
            try:
                arguments = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(ToolCall(id=call["id"], name=call["name"], arguments=arguments))
        yield LLMResponse(content="".join(content_parts), tool_calls=tool_calls)
