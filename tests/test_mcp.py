"""MCP tool, lifecycle and local-protocol tests."""

from types import SimpleNamespace
import asyncio
from pathlib import Path
import sys
import socket
import subprocess

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.mcp import McpService
from zhiyu.cli.main import _normalize_cli_args, _parser
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


def test_mcp_add_cli_supports_dash_prefixed_arguments():
    args = _parser().parse_args(
        _normalize_cli_args(["mcp", "add", "files", "npx", "--arg", "-y"])
    )
    assert args.arg == ["-y"]


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


async def test_connection_against_local_real_stdio_mcp_server():
    fixture = Path(__file__).parent / "fixtures" / "mcp_stdio_echo.py"
    connection = McpConnection("echo", sys.executable, [str(fixture)])
    try:
        tools = await connection.connect()
        assert [tool.name for tool in tools] == ["echo.echo"]
        assert await tools[0].execute(text="protocol smoke") == "protocol smoke"
    finally:
        await connection.close()


async def test_connection_against_local_real_streamable_http_server():
    fixture = Path(__file__).parent / "fixtures" / "mcp_stdio_echo.py"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, str(fixture), "http", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    connection = McpConnection(
        "echo", transport="streamable_http", url=f"http://127.0.0.1:{port}/mcp"
    )
    try:
        for _ in range(50):
            if process.poll() is not None:
                raise AssertionError("本地 MCP HTTP 测试服务器意外退出")
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("本地 MCP HTTP 测试服务器未就绪")
        try:
            await connection.connect()
        except Exception:
            await connection.close()
            raise
        assert [tool.name for tool in connection.tools] == ["echo.echo"]
        assert await connection.tools[0].execute(text="http smoke") == "http smoke"
        assert await connection.read_resource("test://data") == "resource smoke"
        assert await connection.get_prompt("greet", {"name": "Ada"}) == "Hello, Ada!"
    finally:
        try:
            await connection.close()
        except BaseException:
            pass
        process.terminate()
        process.wait(timeout=5)


async def test_unreachable_http_server_is_a_connection_error_not_task_cancel():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    connection = McpConnection(
        "missing", transport="streamable_http", url=f"http://127.0.0.1:{port}/mcp"
    )
    try:
        try:
            await asyncio.wait_for(connection.connect(), timeout=2)
        except ConnectionError:
            pass
        else:
            raise AssertionError("不可达 MCP 应作为连接错误交给 supervisor 重试")
    finally:
        try:
            await connection.close()
        except BaseException:
            pass


async def test_connection_against_local_real_legacy_sse_server():
    fixture = Path(__file__).parent / "fixtures" / "mcp_stdio_echo.py"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, str(fixture), "sse", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    connection = McpConnection(
        "echo", transport="sse", url=f"http://127.0.0.1:{port}/sse"
    )
    try:
        for _ in range(50):
            if process.poll() is not None:
                raise AssertionError("本地 MCP SSE 测试服务器意外退出")
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("本地 MCP SSE 测试服务器未就绪")
        await connection.connect()
        assert await connection.tools[0].execute(text="sse smoke") == "sse smoke"
    finally:
        try:
            await connection.close()
        except BaseException:
            pass
        process.terminate()
        process.wait(timeout=5)
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


def test_http_mcp_keeps_secrets_out_of_configuration_rows():
    class MemorySecrets:
        def __init__(self):
            self.values = {}

        def set(self, ref, value):
            self.values[ref] = value

        def get(self, ref):
            return self.values.get(ref)

        def delete(self, ref):
            self.values.pop(ref, None)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    secrets = MemorySecrets()
    service = McpService(sessions, secrets=secrets)

    service.configure(
        "docs", None, [], transport="streamable_http", url="https://mcp.example.com/mcp"
    )
    service.set_header_secret("docs", "Authorization", "Bearer secret-value")
    config = service.get("docs")
    listed = service.list()[0]

    assert config["command"] is None
    assert config["url"] == "https://mcp.example.com/mcp"
    assert "secret-value" not in str(config)
    assert "secret-value" not in str(listed)
    assert listed.secret_names == ["header:Authorization"]
    assert len(secrets.values) == 1
