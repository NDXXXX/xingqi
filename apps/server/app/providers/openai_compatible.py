"""OpenAI 兼容 Provider（DeepSeek / MiniMax / Kimi / OpenAI）。"""

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from .base import AIProvider, LLMResponse, ToolCall


class OpenAICompatibleProvider(AIProvider):
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
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if tools:
            payload["tools"] = tools
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        if not stream:
            async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
                resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            return self._parse_completion(data)

        return self._stream(headers, payload)

    @staticmethod
    def _parse_completion(data: dict[str, Any]) -> LLMResponse:
        message = data["choices"][0].get("message", {})
        content = message.get("content") or ""
        tool_calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function", {})
            try:
                arguments = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(
                ToolCall(id=raw.get("id", ""), name=fn.get("name", ""), arguments=arguments)
            )
        return LLMResponse(content=content, tool_calls=tool_calls)

    async def _stream(
        self, headers: dict[str, str], payload: dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            async with client.stream(
                "POST", f"{self.base_url}/chat/completions", headers=headers, json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    delta = json.loads(data)["choices"][0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta
