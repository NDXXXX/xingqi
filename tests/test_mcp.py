"""MCP 工具适配与 Manager 测试（不启动真实 MCP 服务器）。"""

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.mcp import McpService
from zhiyu.integrations.mcp.connection import McpConnection, McpTool
from zhiyu.integrations.mcp.manager import McpManager
from zhiyu.infrastructure.database.db import Base


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


async def test_connection_namespaces_tools(monkeypatch):
    calls = []

    class FakeContext:
        async def __aenter__(self):
            return object(), object()

        async def __aexit__(self, *_args):
            return None

    class FakeSession(FakeContext):
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(
                tools=[SimpleNamespace(name="read_file", description="read", input_schema={})]
            )

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return SimpleNamespace(content=[SimpleNamespace(text="ok")])

    monkeypatch.setattr("zhiyu.integrations.mcp.connection.stdio_client", lambda _params: FakeContext())
    monkeypatch.setattr("zhiyu.integrations.mcp.connection.ClientSession", FakeSession)

    connection = McpConnection("filesystem", "fake", [])
    tools = await connection.connect()

    assert tools[0].name == "filesystem.read_file"
    assert await tools[0].execute(path="/tmp/a") == "ok"
    assert calls == [("read_file", {"path": "/tmp/a"})]
    await connection.close()


async def test_manager_filters_tools_with_allowlist(monkeypatch):
    async def fake_call(_args):
        return "ok"

    class FakeConnection:
        def __init__(self, name, command, args):
            self.name = name
            self.command = command
            self.args = args
            self.tools = []

        async def connect(self):
            self.tools = [
                McpTool("files.read", "read", {}, fake_call),
                McpTool("files.write", "write", {}, fake_call),
            ]
            return self.tools

        async def close(self):
            return None

    monkeypatch.setattr("zhiyu.integrations.mcp.manager.McpConnection", FakeConnection)
    manager = McpManager()

    tools = await manager.connect(
        "files",
        "fake",
        [],
        tool_allowlist=["read"],
    )

    assert [tool.name for tool in tools] == ["files.read"]
    assert [tool.name for tool in manager.tools()] == ["files.read"]


def test_mcp_service_persists_allowlist():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    service = McpService(sessions)

    service.configure(
        "files",
        "mcp-files",
        ["--root", "/tmp/work"],
        ["read_file"],
    )

    item = service.list()[0]
    assert item.name == "files"
    assert item.args == ["--root", "/tmp/work"]
    assert item.tool_allowlist == ["read_file"]
