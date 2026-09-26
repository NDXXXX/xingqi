"""Anthropic Provider（Messages API）。"""

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from .base import AIProvider, LLMResponse, ToolCall


class AnthropicProvider(AIProvider):
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
        payload: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": 1024, "stream": stream}
        if tools:
            payload["tools"] = tools
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
    ) -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            async with client.stream(
                "POST", f"{self.base_url}/v1/messages", headers=headers, json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = json.loads(line[5:].strip())
                    if data.get("type") == "content_block_delta":
                        text = data.get("delta", {}).get("text", "")
                        if text:
                            yield text
