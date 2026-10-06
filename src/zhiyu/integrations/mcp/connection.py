"""MCP client transports and Agent tool adapters."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import AsyncExitStack
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import McpHttpClientFactory

from zhiyu.core.tools.base import AgentTool


class McpTool(AgentTool):
    """Wrap an MCP capability as an AgentTool."""

    timeout_seconds = 30

    def __init__(self, name: str, description: str, schema: dict, call):
        self.name = name
        self.description = description
        self.schema = schema
        self._call = call

    async def execute(self, **kwargs):
        return await self._call(kwargs)


class McpConnection:
    """One stdio, Streamable HTTP, or legacy SSE MCP connection."""

    def __init__(
        self,
        name: str,
        command: str | None = None,
        args: list[str] | None = None,
        *,
        transport: str = "stdio",
        url: str | None = None,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.name = name
        self.command = command or ""
        self.args = args or []
        self.transport = transport
        self.url = url
        self.env = env or {}
        self.headers = headers or {}
        self.tools: list[McpTool] = []
        self.resources: list[dict[str, Any]] = []
        self.prompts: list[dict[str, Any]] = []
        self.server_info: dict[str, Any] = {}
        self.capabilities: dict[str, bool] = {}
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._http_client: httpx2.AsyncClient | None = None

    async def connect(self) -> list[McpTool]:
        try:
            return await self._connect()
        except BaseException as exc:
            cleanup_error = None
            try:
                await self.close()
            except BaseException as close_exc:
                cleanup_error = close_exc
            transport_error = _first_non_cancellation_error(cleanup_error)
            if isinstance(exc, asyncio.CancelledError) and transport_error is not None:
                raise ConnectionError(f"MCP transport failed: {transport_error}") from transport_error
            raise

    async def _connect(self) -> list[McpTool]:
        stack = AsyncExitStack()
        self._stack = stack
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio MCP 缺少启动命令")
            read, write = await stack.enter_async_context(
                stdio_client(
                    StdioServerParameters(
                        command=self.command,
                        args=self.args,
                        env=self.env,
                    )
                )
            )
        elif self.transport in {"streamable_http", "sse"}:
            if not self.url:
                raise ValueError("HTTP MCP 缺少 URL")
            if self.transport == "streamable_http":
                self._http_client = httpx2.AsyncClient(
                    headers=self.headers,
                    timeout=httpx2.Timeout(30.0, read=300.0),
                    trust_env=False,
                )
                await stack.enter_async_context(self._http_client)
                read, write = await stack.enter_async_context(
                    streamable_http_client(self.url, http_client=self._http_client)
                )
            else:
                factory: McpHttpClientFactory = lambda headers=None, timeout=None, auth=None: (
                    httpx2.AsyncClient(
                        headers=headers,
                        timeout=timeout or httpx2.Timeout(30.0, read=300.0),
                        auth=auth,
                        trust_env=False,
                    )
                )
                read, write = await stack.enter_async_context(
                    sse_client(
                        self.url,
                        headers=self.headers,
                        httpx_client_factory=factory,
                    )
                )
        else:
            raise ValueError(f"不支持的 MCP 传输：{self.transport}")

        self._session = await stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        info = getattr(self._session, "server_info", None)
        self.server_info = {
            "name": getattr(info, "name", None),
            "version": getattr(info, "version", None),
        }
        server_capabilities = getattr(self._session, "server_capabilities", None)
        self.capabilities = {
            "tools": True if server_capabilities is None else bool(getattr(server_capabilities, "tools", None)),
            "resources": bool(getattr(server_capabilities, "resources", None)),
            "prompts": bool(getattr(server_capabilities, "prompts", None)),
        }
        await self.refresh()
        return self.tools

    async def refresh(self) -> None:
        try:
            await self._refresh()
        except BaseException as exc:
            cleanup_error = None
            try:
                await self.close()
            except BaseException as close_exc:
                cleanup_error = close_exc
            transport_error = _first_non_cancellation_error(cleanup_error)
            if isinstance(exc, asyncio.CancelledError) and transport_error is not None:
                raise ConnectionError(f"MCP transport failed: {transport_error}") from transport_error
            raise

    async def _refresh(self) -> None:
        if self._session is None:
            raise ConnectionError("MCP 尚未连接")
        if self.capabilities.get("tools"):
            result = await self._session.list_tools()
            self.tools = []
            for item in result.tools:
                schema_value = getattr(item, "inputSchema", None) or getattr(
                    item, "input_schema", None
                )
                schema = schema_value if isinstance(schema_value, dict) else {}
                if not schema:
                    schema = {"type": "object", "properties": {}}
                self.tools.append(
                    McpTool(
                        f"{self.name}.{item.name}",
                        item.description or "",
                        schema,
                        self._make_call(item.name),
                    )
                )
        if self.capabilities.get("resources"):
            result = await self._session.list_resources()
            self.resources = [
                {
                    "name": item.name,
                    "description": item.description,
                    "mime_type": getattr(item, "mimeType", None) or getattr(item, "mime_type", None),
                    "uri": str(item.uri),
                }
                for item in result.resources
            ]
        if self.capabilities.get("prompts"):
            result = await self._session.list_prompts()
            self.prompts = [
                {
                    "name": item.name,
                    "description": item.description,
                    "arguments": [
                        {
                            "name": arg.name,
                            "description": arg.description,
                            "required": bool(arg.required),
                        }
                        for arg in (item.arguments or [])
                    ],
                }
                for item in result.prompts
            ]

    def _make_call(self, name: str):
        async def call(arguments: dict) -> str:
            return await self.call_tool(name, arguments)

        return call

    async def call_tool(self, name: str, arguments: dict) -> str:
        if self._session is None:
            raise ConnectionError("MCP 尚未连接")
        result = await self._session.call_tool(name, arguments)
        parts = []
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(text)
        if parts:
            return "\n".join(parts)
        sc = getattr(result, "structuredContent", None)
        if sc is None:
            sc = getattr(result, "structured_content", None)
        if sc is not None:
            return sc if isinstance(sc, str) else json.dumps(sc, ensure_ascii=False)
        return ""

    async def read_resource(self, uri: str, *, max_bytes: int = 1_000_000) -> str:
        if self._session is None:
            raise ConnectionError("MCP 尚未连接")
        result = await self._session.read_resource(uri)
        values = []
        total = 0
        for item in result.contents:
            value = getattr(item, "text", None)
            if value is None:
                value = f"[非文本资源: {getattr(item, 'mimeType', None) or '未知类型'}]"
            total += len(value.encode("utf-8"))
            if total > max_bytes:
                raise ValueError("MCP Resource 超过 1 MB 限制")
            values.append(value)
        return "\n".join(values)

    async def get_prompt(self, name: str, arguments: dict[str, str]) -> str:
        if self._session is None:
            raise ConnectionError("MCP 尚未连接")
        result = await self._session.get_prompt(name, arguments)
        values = []
        for message in result.messages:
            content = getattr(message, "content", [])
            if isinstance(content, str):
                values.append(content)
                continue
            blocks = content if isinstance(content, list) else [content]
            values.extend(
                text
                for block in blocks
                if (text := getattr(block, "text", None)) is not None
            )
        return "\n".join(values)

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self._session = None
        self.tools.clear()
        if stack is not None:
            await stack.aclose()


def safe_error(exc: BaseException, secrets: list[str] | None = None) -> str:
    message = str(exc).replace("\n", " ").strip()[:500]
    for secret in secrets or []:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", message)
    return message or type(exc).__name__


def _first_non_cancellation_error(exc: BaseException | None) -> BaseException | None:
    if exc is None:
        return None
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            found = _first_non_cancellation_error(child)
            if found is not None:
                return found
        return None
    if isinstance(exc, asyncio.CancelledError):
        return None
    return exc
