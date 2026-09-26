"""MCP 工具适配与 Manager 测试（不启动真实 MCP 服务器）。"""

from app.mcp.connection import McpTool
from app.mcp.manager import McpManager


async def test_mcp_tool_conversion_and_execute():
    async def fake_call(args: dict) -> str:
        return f"echo:{args.get('text')}"

    tool = McpTool(
        "echo",
        "回显输入",
        {"type": "object", "properties": {"text": {"type": "string"}}},
        fake_call,
    )
    oai = tool.to_openai_tool()
    assert oai["type"] == "function"
    assert oai["function"]["name"] == "echo"
    assert oai["function"]["parameters"]["properties"]["text"]["type"] == "string"
    assert await tool.execute(text="hi") == "echo:hi"


async def test_manager_tools_and_list():
    async def fake_call(args: dict) -> str:
        return "x"

    class FakeConn:
        def __init__(self):
            self.name = "fake"
            self.command = "cmd"
            self.args = []
            self.tools = [McpTool("echo", "回显", {"type": "object", "properties": {}}, fake_call)]

    mgr = McpManager()
    mgr._connections["fake"] = FakeConn()
    assert [t.name for t in mgr.tools()] == ["echo"]
    assert mgr.servers() == [{"name": "fake", "command": "cmd", "args": [], "connected": True, "tools": ["echo"]}]
