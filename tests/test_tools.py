"""内置工具与 ToolRegistry 测试。"""

import pytest

from zhiyu.core.tools.calculator import CalculatorTool
from zhiyu.core.tools.datetime import DateTimeTool
from zhiyu.core.tools.registry import default_registry


async def test_calculator_basic():
    tool = CalculatorTool()
    assert await tool.execute(expression="2 + 3 * 4") == 14
    assert await tool.execute(expression="(1 + 2) * 3") == 9
    assert await tool.execute(expression="2 ** 10") == 1024


async def test_calculator_rejects_unsafe():
    tool = CalculatorTool()
    with pytest.raises(ValueError):
        await tool.execute(expression="__import__('os').system('ls')")
    with pytest.raises(ValueError):
        await tool.execute(expression="hello")


async def test_datetime():
    result = await DateTimeTool().execute()
    assert isinstance(result, str) and result


async def test_registry_contains_builtins_and_schema():
    registry = default_registry()
    assert set(registry.names()) == {"calculator", "datetime"}
    tools = registry.to_openai_tools()
    assert all(t["type"] == "function" for t in tools)
    assert {t["function"]["name"] for t in tools} == {"calculator", "datetime"}
