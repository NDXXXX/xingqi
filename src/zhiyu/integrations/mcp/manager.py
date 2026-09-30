"""MCP Manager：管理 MCP 服务器连接与工具注册。"""

from zhiyu.core.tools.base import AgentTool
from .connection import McpConnection, McpTool


class McpManager:
    def __init__(self) -> None:
        self._connections: dict[str, McpConnection] = {}

    async def connect(self, name: str, command: str, args: list[str]) -> list[McpTool]:
        if name in self._connections:
            await self.disconnect(name)
        conn = McpConnection(name, command, args)
        tools = await conn.connect()
        self._connections[name] = conn
        return tools

    async def disconnect(self, name: str) -> bool:
        conn = self._connections.pop(name, None)
        if conn is None:
            return False
        await conn.close()
        return True

    def servers(self) -> list[dict]:
        return [
            {
                "name": c.name,
                "command": c.command,
                "args": c.args,
                "connected": True,
                "tools": [t.name for t in c.tools],
            }
            for c in self._connections.values()
        ]

    def tools(self) -> list[AgentTool]:
        out: list[AgentTool] = []
        for conn in self._connections.values():
            out.extend(conn.tools)
        return out

    async def close_all(self) -> None:
        for conn in list(self._connections.values()):
            await conn.close()
        self._connections.clear()


default_manager = McpManager()
