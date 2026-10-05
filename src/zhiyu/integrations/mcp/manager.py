"""MCP Manager：管理 MCP 服务器连接、恢复与工具白名单。"""

import asyncio

from zhiyu.core.tools.base import AgentTool
from .connection import McpConnection, McpTool


class McpManager:
    def __init__(self) -> None:
        self._connections: dict[str, McpConnection] = {}

    async def connect(
        self,
        name: str,
        command: str,
        args: list[str],
        *,
        tool_allowlist: list[str] | None = None,
    ) -> list[McpTool]:
        if name in self._connections:
            await self.disconnect(name)
        conn = McpConnection(name, command, args)
        try:
            tools = await conn.connect()
        except Exception:
            await conn.close()
            raise
        if tool_allowlist:
            allowed = set(tool_allowlist)
            tools = [
                tool
                for tool in tools
                if tool.name in allowed or tool.name.removeprefix(f"{name}.") in allowed
            ]
            conn.tools = tools
        self._connections[name] = conn
        return tools

    async def connect_with_retry(
        self,
        name: str,
        command: str,
        args: list[str],
        *,
        tool_allowlist: list[str] | None = None,
        attempts: int = 2,
        timeout_seconds: float = 10,
    ) -> list[McpTool]:
        last_error: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                return await asyncio.wait_for(
                    self.connect(
                        name,
                        command,
                        args,
                        tool_allowlist=tool_allowlist,
                    ),
                    timeout=timeout_seconds,
                )
            except Exception as exc:
                last_error = exc
                await self.disconnect(name)
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.25 * (attempt + 1))
        assert last_error is not None
        raise last_error

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
