"""MCP 连接与工具适配：把 MCP 工具包装成 AgentTool。"""

import json

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from ..tools.base import AgentTool


class McpTool(AgentTool):
    """包装一个 MCP 工具为 AgentTool，execute 时回调 call(arguments)。"""

    def __init__(self, name: str, description: str, schema: dict, call):
        self.name = name
        self.description = description
        self.schema = schema
        self._call = call

    async def execute(self, **kwargs):
        return await self._call(kwargs)


class McpConnection:
    """一个 MCP stdio 服务器连接。"""

    def __init__(self, name: str, command: str, args: list[str]):
        self.name = name
        self.command = command
        self.args = args
        self.tools: list[McpTool] = []
        self._stdio_cm = None
        self._session_cm = None
        self._session = None

    async def connect(self) -> list[McpTool]:
        params = StdioServerParameters(command=self.command, args=self.args)
        self._stdio_cm = stdio_client(params)
        read, write = await self._stdio_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        result = await self._session.list_tools()
        self.tools = []
        for t in result.tools:
            schema = t.input_schema if isinstance(t.input_schema, dict) else {}
            if not schema:
                schema = {"type": "object", "properties": {}}
            self.tools.append(McpTool(t.name, t.description or "", schema, self._make_call(t.name)))
        return self.tools

    def _make_call(self, name: str):
        async def call(arguments: dict) -> str:
            return await self.call_tool(name, arguments)

        return call

    async def call_tool(self, name: str, arguments: dict) -> str:
        result = await self._session.call_tool(name, arguments)
        parts = []
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(text)
        if parts:
            return "\n".join(parts)
        sc = getattr(result, "structured_content", None)
        if sc is not None:
            return sc if isinstance(sc, str) else json.dumps(sc, ensure_ascii=False)
        return ""

    async def close(self) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(None, None, None)
        if self._stdio_cm is not None:
            await self._stdio_cm.__aexit__(None, None, None)
