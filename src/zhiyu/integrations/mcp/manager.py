"""MCP connection supervision, capability filtering and status snapshots."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
from datetime import datetime, timezone
from typing import Callable

from zhiyu.core.tools.base import AgentTool

from .connection import McpConnection, McpTool, safe_error


logger = logging.getLogger(__name__)


class McpResourceTool(AgentTool):
    timeout_seconds = 30

    def __init__(self, server: str, connection: McpConnection, allowed: list[str]):
        self.name = f"{server}.read_resource"
        self.description = "读取此 MCP Server 中明确授权的只读资源。"
        self.schema = {
            "type": "object",
            "properties": {"uri": {"type": "string"}},
            "required": ["uri"],
        }
        self.connection = connection
        self.allowed = allowed

    async def execute(self, uri: str) -> str:
        if not any(_resource_allowed(uri, rule) for rule in self.allowed):
            raise ValueError("MCP Resource 未授权")
        return await self.connection.read_resource(uri)


class McpPromptTool(AgentTool):
    timeout_seconds = 30

    def __init__(self, server: str, connection: McpConnection, prompt: dict):
        self.prompt_name = prompt["name"]
        self.name = f"{server}.prompt_{self.prompt_name}"
        self.description = prompt.get("description") or "运行已授权的 MCP Prompt。"
        arguments = prompt.get("arguments", [])
        self.schema = {
            "type": "object",
            "properties": {
                item["name"]: {
                    "type": "string",
                    **({"description": item["description"]} if item.get("description") else {}),
                }
                for item in arguments
            },
            "required": [item["name"] for item in arguments if item.get("required")],
        }
        self.connection = connection

    async def execute(self, **kwargs) -> str:
        return await self.connection.get_prompt(self.prompt_name, kwargs)


class McpManager:
    def __init__(self, state_writer: Callable | None = None) -> None:
        self._connections: dict[str, McpConnection] = {}
        self._configs: dict[str, dict] = {}
        self._signatures: dict[str, str] = {}
        self._states: dict[str, dict] = {}
        self._supervisors: dict[str, asyncio.Task] = {}
        self._wakeups: dict[str, asyncio.Event] = {}
        self._state_writer = state_writer

    async def connect(
        self,
        name: str,
        command: str | None,
        args: list[str],
        *,
        tool_allowlist: list[str] | None = None,
        legacy_all_tools: bool = False,
        transport: str = "stdio",
        url: str | None = None,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        resource_allowlist: list[str] | None = None,
        prompt_allowlist: list[str] | None = None,
    ) -> list[McpTool]:
        await self.disconnect(name)
        if transport == "stdio" and url is None and not env and not headers:
            conn = McpConnection(name, command, args)
        else:
            conn = McpConnection(
                name,
                command,
                args,
                transport=transport,
                url=url,
                env=env,
                headers=headers,
            )
        try:
            await conn.connect()
        except Exception:
            await conn.close()
            raise
        allowed = set(tool_allowlist or [])
        if legacy_all_tools:
            allowed.update(tool.name.removeprefix(f"{name}.") for tool in conn.tools)
        conn.discovered_tools = list(conn.tools)
        conn.tools = [
            tool
            for tool in conn.tools
            if tool.name.removeprefix(f"{name}.") in allowed
            or tool.name in allowed
        ]
        key = name
        self._connections[key] = conn
        self._configs[key] = {
            "name": name,
            "command": command,
            "args": args,
            "transport": transport,
            "tool_allowlist": list(allowed),
            "resource_allowlist": resource_allowlist or [],
            "prompt_allowlist": prompt_allowlist or [],
        }
        return conn.tools

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
                    self.connect(name, command, args, tool_allowlist=tool_allowlist),
                    timeout=timeout_seconds,
                )
            except Exception as exc:
                last_error = exc
                await self.disconnect(name)
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.25 * (attempt + 1))
        assert last_error is not None
        raise last_error

    async def reconcile(self, configs: list[dict]) -> None:
        desired = {str(item.get("id") or item["name"]): item for item in configs}
        for key in list(self._supervisors):
            if key not in desired:
                await self._stop_supervisor(key)
        for key, config in desired.items():
            signature = _fingerprint(config)
            if self._signatures.get(key) == signature:
                continue
            await self._stop_supervisor(key)
            self._configs[key] = config
            self._signatures[key] = signature
            wake = asyncio.Event()
            self._wakeups[key] = wake
            self._set_state(key, config, status="connecting", retry_count=0)
            self._supervisors[key] = asyncio.create_task(
                self._supervise(key, config, wake), name=f"mcp:{config['name']}"
            )

    async def _supervise(self, key: str, config: dict, wake: asyncio.Event) -> None:
        retry_count = 0
        while True:
            connection = None
            try:
                if config.get("preflight_error"):
                    raise ValueError(config["preflight_error"])
                connection = McpConnection(
                    config["name"],
                    config.get("command"),
                    config.get("args", []),
                    transport=config.get("transport", "stdio"),
                    url=config.get("url"),
                    env=config.get("env", {}),
                    headers=config.get("headers", {}),
                )
                await asyncio.wait_for(connection.connect(), timeout=30)
                self._connections[key] = connection
                retry_count = 0
                self._set_state(
                    key,
                    config,
                    status="ready",
                    retry_count=0,
                    connected_at=datetime.now(timezone.utc).isoformat(),
                    last_success_at=datetime.now(timezone.utc).isoformat(),
                    last_error=None,
                    last_error_code=None,
                    next_retry_at=None,
                    server_info=connection.server_info,
                    capabilities=connection.capabilities,
                )
                while True:
                    wake.clear()
                    try:
                        await asyncio.wait_for(wake.wait(), timeout=30)
                        break
                    except TimeoutError:
                        await asyncio.wait_for(connection.refresh(), timeout=15)
                        self._set_state(
                            key,
                            config,
                            status="ready",
                            retry_count=0,
                            last_success_at=datetime.now(timezone.utc).isoformat(),
                            server_info=connection.server_info,
                            capabilities=connection.capabilities,
                        )
                await connection.close()
                self._connections.pop(key, None)
                self._set_state(key, config, status="connecting", retry_count=retry_count)
            except asyncio.CancelledError:
                if connection is not None:
                    await connection.close()
                raise
            except Exception as exc:
                retry_count += 1
                if connection is not None:
                    await connection.close()
                self._connections.pop(key, None)
                delay = min(300.0, 2 ** min(retry_count - 1, 8))
                delay *= random.uniform(0.8, 1.2)
                error = safe_error(exc, config.get("secret_values", []))
                self._set_state(
                    key,
                    config,
                    status="degraded",
                    retry_count=retry_count,
                    last_error_code=type(exc).__name__,
                    last_error=error,
                    next_retry_at=datetime.fromtimestamp(
                        datetime.now(timezone.utc).timestamp() + delay,
                        timezone.utc,
                    ).isoformat(),
                )
                wake.clear()
                try:
                    await asyncio.wait_for(wake.wait(), timeout=delay)
                except TimeoutError:
                    pass

    def _set_state(self, key: str, config: dict, **values) -> None:
        state = {**self._states.get(key, {}), **values}
        state.update(name=config.get("name"), server_config_id=config.get("id"))
        self._states[key] = state
        if self._state_writer and config.get("id"):
            try:
                self._state_writer(config["id"], state)
            except Exception:
                logger.exception("Unable to persist MCP runtime state for %s", config.get("name"))

    async def _stop_supervisor(self, key: str) -> None:
        wake = self._wakeups.pop(key, None)
        if wake is not None:
            wake.set()
        task = self._supervisors.pop(key, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        connection = self._connections.pop(key, None)
        if connection is not None:
            await connection.close()
        config = self._configs.pop(key, None)
        self._signatures.pop(key, None)
        if config is not None:
            self._set_state(key, config, status="stopped", retry_count=0, next_retry_at=None)

    async def reconnect(self, name: str, character_id: str | None = None) -> bool:
        key = next(
            (key for key, config in self._configs.items() if config.get("name") == name and config.get("character_id") == character_id),
            None,
        )
        if key is None:
            return False
        wake = self._wakeups.get(key)
        if wake is None:
            return False
        wake.set()
        return True

    async def disconnect(self, name: str, character_id: str | None = None) -> bool:
        key = next(
            (key for key, config in self._configs.items() if config.get("name") == name and config.get("character_id") == character_id),
            None,
        )
        if key is None:
            return False
        if key in self._supervisors:
            await self._stop_supervisor(key)
            return True
        connection = self._connections.pop(key, None)
        if connection is not None:
            await connection.close()
        self._configs.pop(key, None)
        return connection is not None

    def servers(self) -> list[dict]:
        items = []
        for key, state in self._states.items():
            config = self._configs.get(key, {})
            items.append(
                {
                    "name": config.get("name", state.get("name")),
                    "transport": config.get("transport", "stdio"),
                    "connected": state.get("status") == "ready",
                    "status": state.get("status", "stopped"),
                    "tools": [item.name for item in self._tools_for(key)],
                    "resources": len(getattr(self._connections[key], "resources", []))
                    if key in self._connections
                    else 0,
                    "prompts": len(getattr(self._connections[key], "prompts", []))
                    if key in self._connections
                    else 0,
                    "last_error": state.get("last_error"),
                    "retry_count": state.get("retry_count", 0),
                }
            )
        for key, connection in self._connections.items():
            if key not in self._states:
                config = self._configs.get(key, {})
                items.append(
                    {
                        "name": config.get("name", connection.name),
                        "command": config.get("command", connection.command),
                        "args": config.get("args", connection.args),
                        "connected": True,
                        "tools": [item.name for item in self._tools_for(key)],
                    }
                )
        return items

    def _tools_for(self, key: str) -> list[AgentTool]:
        connection = self._connections.get(key)
        config = self._configs.get(key, {})
        if connection is None:
            return []
        if not config:
            return list(connection.tools)
        name = config.get("name", connection.name)
        allowed = set(config.get("tool_allowlist", []))
        if config.get("legacy_all_tools"):
            allowed.update(tool.name.removeprefix(f"{name}.") for tool in connection.tools)
        tools: list[AgentTool] = [
            tool
            for tool in connection.tools
            if tool.name.removeprefix(f"{name}.") in allowed or tool.name in allowed
        ]
        resource_allowlist = config.get("resource_allowlist", [])
        if resource_allowlist:
            tools.append(McpResourceTool(name, connection, resource_allowlist))
        prompt_allowlist = set(config.get("prompt_allowlist", []))
        for prompt in getattr(connection, "prompts", []):
            if prompt["name"] in prompt_allowlist:
                tools.append(McpPromptTool(name, connection, prompt))
        return tools

    def tools(self, character_id: str | None = None) -> list[AgentTool]:
        out: list[AgentTool] = []
        for key in self._connections:
            if self._configs.get(key, {}).get("character_id") == character_id:
                out.extend(self._tools_for(key))
        return out

    def connection(self, name: str, character_id: str | None = None) -> McpConnection | None:
        key = next(
            (key for key, config in self._configs.items() if config.get("name") == name and config.get("character_id") == character_id),
            None,
        )
        return self._connections.get(key)

    async def close_all(self) -> None:
        for key in list(self._supervisors):
            await self._stop_supervisor(key)
        for conn in list(self._connections.values()):
            await conn.close()
        self._connections.clear()
        self._configs.clear()


def _resource_allowed(uri: str, rule: str) -> bool:
    return uri.startswith(rule[:-1]) if rule.endswith("*") else uri == rule


def _fingerprint(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, ensure_ascii=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


default_manager = McpManager()
