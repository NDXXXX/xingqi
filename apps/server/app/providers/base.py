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
