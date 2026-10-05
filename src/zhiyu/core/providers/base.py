"""统一 Provider 接口：所有模型必须实现该接口。"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """模型请求的一次工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """非流式 chat 的返回：正文 + 可选工具调用。"""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class AIProvider(ABC):
    """所有 AI Provider 的抽象基类。"""

    def __init__(self, api_key: str | None, base_url: str | None = None):
        self.api_key = api_key
        self.base_url = base_url

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs,
    ) -> LLMResponse | AsyncGenerator[str, None]:
        """stream=False 返回 LLMResponse（含 tool_calls）；stream=True 返回逐块文本的异步生成器。"""
        raise NotImplementedError

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs,
    ) -> AsyncGenerator[str | LLMResponse, None]:
        """逐块返回正文，并以 LLMResponse 作为最后一个事件。

        自定义 Provider 可只实现 ``chat``；支持流时返回异步生成器，不支持时返回
        LLMResponse，默认实现会兼容这两种结果。
        """
        result = await self.chat(messages=messages, tools=tools, stream=True, **kwargs)
        if isinstance(result, LLMResponse):
            if result.content:
                yield result.content
            yield result
            return
        async for item in result:
            yield item
