"""统一 Tool 接口。"""

from abc import ABC, abstractmethod
from typing import Any


class AgentTool(ABC):
    """所有 Agent 工具必须实现该接口。"""

    name: str = ""
    description: str = ""
    schema: dict[str, Any] = {}
    timeout_seconds: int = 15

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        raise NotImplementedError

    def to_openai_tool(self) -> dict[str, Any]:
        """转为 OpenAI function-calling 工具描述。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }
