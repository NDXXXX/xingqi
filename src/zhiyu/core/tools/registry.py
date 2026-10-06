"""Tool Registry：注册 / 查询 / 转为 OpenAI 工具格式。"""

from .base import AgentTool
from .calculator import CalculatorTool
from .datetime import DateTimeTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    def all(self) -> list[AgentTool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def to_openai_tools(self) -> list[dict]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def filtered(self, allowed: set[str]) -> "ToolRegistry":
        registry = ToolRegistry()
        for name, tool in self._tools.items():
            if name in allowed:
                registry.register(tool)
        return registry


def default_registry() -> ToolRegistry:
    """内置工具集（Phase 7：calculator + datetime）。"""
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(DateTimeTool())
    return registry
