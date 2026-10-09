"""MCP server configuration, credentials and capability inspection."""

from __future__ import annotations

import json
import ipaddress
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from zhiyu.infrastructure.config.keystore import KeyStore, keystore
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.integration_repository import (
    McpConfigRepository,
    McpRuntimeStateRepository,
)
from zhiyu.infrastructure.database.repositories.setting_repository import SettingRepository

from zhiyu.integrations.mcp.connection import McpConnection, safe_error


NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
SENSITIVE_QUERY_KEYS = {"token", "access_token", "api_key", "apikey", "secret", "auth"}
BASE_CHILD_ENV = ("PATH", "HOME", "USER", "TMPDIR", "TEMP", "LANG", "LC_ALL")
CONFIG_REVISION_KEY = "integration_config_revision"


@dataclass(slots=True)
class McpServerSummary:
    id: str
    name: str
    transport: str
    command: str | None
    args: list[str]
    url: str | None
    env_names: list[str]
    secret_names: list[str]
    tool_allowlist: list[str]
    legacy_all_tools: bool
    resource_allowlist: list[str]
    prompt_allowlist: list[str]
    enabled: bool
    auto_connect: bool
    status: str
    connected_at: str | None
    last_success_at: str | None
    last_error: str | None
    retry_count: int
    next_retry_at: str | None
    server_info: dict
    capabilities: dict


class McpService:
    def __init__(self, session_factory=SessionLocal, secrets: KeyStore = keystore, character_id: str | None = None) -> None:
        self.session_factory = session_factory
        self.configs = McpConfigRepository(character_id)
        self.states = McpRuntimeStateRepository()
        self.settings = SettingRepository()
        self.secrets = secrets

    def list(self) -> list[McpServerSummary]:
        with self.session_factory() as db:
            result = []
            for item in self.configs.list(db):
                state = self.states.get(db, item.id)
                env = self.configs.json_field(item, "env_json")
                refs = self.configs.json_field(item, "secret_refs_json")
                server_info = json.loads(state.server_info_json) if state and state.server_info_json else {}
                capabilities = json.loads(state.capabilities_json) if state and state.capabilities_json else {}
                result.append(
                    McpServerSummary(
                        id=item.id,
                        name=item.name,
                        transport=item.transport,
                        command=item.command,
                        args=self.configs.args(item),
                        url=item.url,
                        env_names=sorted(env),
                        secret_names=sorted(refs),
                        tool_allowlist=self.configs.tool_allowlist(item),
                        legacy_all_tools=item.legacy_all_tools,
                        resource_allowlist=self.configs.json_field(item, "resource_allowlist_json"),
                        prompt_allowlist=self.configs.json_field(item, "prompt_allowlist_json"),
                        enabled=item.enabled,
                        auto_connect=item.auto_connect,
                        status=state.status if state else ("stopped" if not item.enabled else "unknown"),
                        connected_at=_iso(state.connected_at) if state else None,
                        last_success_at=_iso(state.last_success_at) if state else None,
                        last_error=state.last_error if state else None,
                        retry_count=state.retry_count if state else 0,
                        next_retry_at=_iso(state.next_retry_at) if state else None,
                        server_info=server_info,
                        capabilities=capabilities,
                    )
                )
            return result

    def get(self, name: str) -> dict:
        with self.session_factory() as db:
            item = self.configs.get(db, name)
            if item is None:
                raise ValueError("MCP Server 不存在")
            return _config_dict(item, self.configs)

    def web_detail(self, name: str) -> dict:
        config = self.get(name)
        refs = config.pop("secret_refs", {})
        config["secret_names"] = sorted(refs)
        return config

    def configure(
        self,
        name: str,
        command: str | None,
        args: list[str],
        tool_allowlist: list[str] | None = None,
        *,
        transport: str = "stdio",
        url: str | None = None,
        enabled: bool = False,
    ) -> McpServerSummary:
        self._validate_name(name)
        if transport == "stdio":
            if not command or not command.strip():
                raise ValueError("stdio MCP 必须提供启动命令")
            if url:
                raise ValueError("stdio MCP 不能设置 URL")
        elif transport in {"streamable_http", "sse"}:
            self._validate_url(transport, url)
            command = None
            args = []
        else:
            raise ValueError("传输类型必须是 stdio、streamable_http 或 sse")

        with self.session_factory() as db:
            old = self.configs.get(db, name)
            if old is None:
                item = self.configs.upsert(
                    db,
                    name,
                    command or "",
                    args,
                    tool_allowlist=tool_allowlist or [],
                    enabled=enabled,
                )
                self.configs.update_fields(
                    db,
                    name,
                    transport=transport,
                    command=command,
                    args_json=json.dumps(args, ensure_ascii=False),
                    url=url,
                    enabled=enabled,
                    auto_connect=enabled,
                )
                item = self.configs.get(db, name)
            else:
                self.configs.update_fields(
                    db,
                    name,
                    transport=transport,
                    command=command,
                    args_json=json.dumps(args, ensure_ascii=False),
                    url=url,
                    enabled=enabled,
                    auto_connect=enabled,
                    **(
                        {"tool_allowlist_json": json.dumps(tool_allowlist, ensure_ascii=False), "legacy_all_tools": False}
                        if tool_allowlist is not None
                        else {}
                    ),
                )
                item = self.configs.get(db, name)
            self._bump_revision(db)
            return self._summary(db, item)

    def set_env(self, name: str, key: str, value: str | None, *, secret: bool = False) -> None:
        self._validate_env_key(key)
        ref_to_delete = None
        new_ref = None
        try:
            with self.session_factory() as db:
                item = self.configs.get(db, name)
                if item is None:
                    raise ValueError("MCP Server 不存在")
                if item.transport != "stdio":
                    raise ValueError("环境变量只适用于 stdio MCP")
                env = self.configs.json_field(item, "env_json")
                refs = self.configs.json_field(item, "secret_refs_json")
                secret_key = f"env:{key}"
                old_ref = refs.pop(secret_key, None)
                if value is None:
                    env.pop(key, None)
                elif secret:
                    new_ref = f"mcp:{item.id}:{uuid4()}"
                    self.secrets.set(new_ref, value)
                    refs[secret_key] = new_ref
                    env.pop(key, None)
                else:
                    env[key] = value
                self.configs.update_fields(
                    db,
                    name,
                    env_json=json.dumps(env, ensure_ascii=False),
                    secret_refs_json=json.dumps(refs, ensure_ascii=False),
                )
                ref_to_delete = old_ref
                self._bump_revision(db)
        except Exception:
            if new_ref:
                self.secrets.delete(new_ref)
            raise
        if ref_to_delete:
            self.secrets.delete(ref_to_delete)

    def set_header_secret(self, name: str, header: str, value: str | None) -> None:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", header):
            raise ValueError("HTTP Header 名称无效")
        new_ref = None
        old_ref = None
        try:
            with self.session_factory() as db:
                item = self.configs.get(db, name)
                if item is None:
                    raise ValueError("MCP Server 不存在")
                if item.transport == "stdio":
                    raise ValueError("stdio MCP 不支持 HTTP Header")
                refs = self.configs.json_field(item, "secret_refs_json")
                ref_key = f"header:{header}"
                old_ref = refs.get(ref_key)
                if value is None:
                    refs.pop(ref_key, None)
                else:
                    new_ref = f"mcp:{item.id}:{uuid4()}"
                    self.secrets.set(new_ref, value)
                    refs[ref_key] = new_ref
                self.configs.update_fields(
                    db,
                    name,
                    secret_refs_json=json.dumps(refs, ensure_ascii=False),
                )
                self._bump_revision(db)
        except Exception:
            if new_ref:
                self.secrets.delete(new_ref)
            raise
        if old_ref and old_ref != new_ref:
            self.secrets.delete(old_ref)

    def set_tool_allowlist(self, name: str, tools: list[str], *, allow_all: bool = False) -> None:
        with self.session_factory() as db:
            item = self.configs.get(db, name)
            if item is None:
                raise ValueError("MCP Server 不存在")
            self.configs.update_fields(
                db,
                name,
                tool_allowlist_json=json.dumps(tools, ensure_ascii=False),
                legacy_all_tools=allow_all,
            )
            self._bump_revision(db)

    def set_capability_allowlist(self, name: str, capability: str, values: list[str]) -> None:
        if capability not in {"resource", "prompt"}:
            raise ValueError("未知 MCP 能力类型")
        field = "resource_allowlist_json" if capability == "resource" else "prompt_allowlist_json"
        with self.session_factory() as db:
            if self.configs.get(db, name) is None:
                raise ValueError("MCP Server 不存在")
            self.configs.update_fields(
                db, name, **{field: json.dumps(values, ensure_ascii=False)}
            )
            self._bump_revision(db)

    def enable(self, name: str, enabled: bool = True) -> None:
        with self.session_factory() as db:
            self.configs.set_enabled(db, name, enabled)
            self._bump_revision(db)

    def request_reconnect(self, name: str) -> None:
        with self.session_factory() as db:
            item = self.configs.get(db, name)
            if item is None:
                raise ValueError("MCP Server 不存在")
            if not item.enabled:
                raise ValueError("请先启用 MCP Server")
            self.configs.update_fields(db, name, updated_at=datetime.now(timezone.utc))
            self._bump_revision(db)

    def remove(self, name: str) -> None:
        refs_to_delete: list[str] = []
        with self.session_factory() as db:
            item = self.configs.get(db, name)
            if item is None:
                raise ValueError("MCP Server 不存在")
            refs = self.configs.json_field(item, "secret_refs_json")
            all_refs = {
                ref
                for config in self.configs.list(db)
                if config.id != item.id
                for ref in self.configs.json_field(config, "secret_refs_json").values()
            }
            refs_to_delete = [ref for ref in refs.values() if ref not in all_refs]
            self.configs.remove(db, name)
            self._bump_revision(db)
        for ref in refs_to_delete:
            self.secrets.delete(ref)

    async def test(self, name: str) -> dict:
        config = self.get(name)
        runtime = self._runtime_config(config)
        connection = McpConnection(
            name,
            runtime["command"],
            runtime["args"],
            transport=runtime["transport"],
            url=runtime["url"],
            env=runtime["env"],
            headers=runtime["headers"],
        )
        try:
            await connection.connect()
            return {
                "name": name,
                "server_info": connection.server_info,
                "capabilities": connection.capabilities,
                "tools": [item.name for item in connection.tools],
                "resources": connection.resources,
                "prompts": connection.prompts,
            }
        except Exception as exc:
            raise ValueError(safe_error(exc, runtime["secret_values"])) from exc
        finally:
            await connection.close()

    async def inspect(self, name: str) -> dict:
        return await self.test(name)

    async def render_prompt(self, name: str, prompt: str, arguments: dict[str, str]) -> str:
        config = self.get(name)
        runtime = self._runtime_config(config)
        if prompt not in config["prompt_allowlist"]:
            raise ValueError("此 MCP Prompt 尚未授权；先执行 zhiyu mcp prompts NAME --allow PROMPT")
        connection = McpConnection(
            name, runtime["command"], runtime["args"], transport=runtime["transport"],
            url=runtime["url"], env=runtime["env"], headers=runtime["headers"],
        )
        try:
            await connection.connect()
            return await connection.get_prompt(prompt, arguments)
        except Exception as exc:
            raise ValueError(safe_error(exc, runtime["secret_values"])) from exc
        finally:
            await connection.close()

    async def read_resource(self, name: str, uri: str) -> str:
        config = self.get(name)
        if not any(_resource_allowed(uri, item) for item in config["resource_allowlist"]):
            raise ValueError("此 MCP Resource 尚未授权")
        runtime = self._runtime_config(config)
        connection = McpConnection(
            name, runtime["command"], runtime["args"], transport=runtime["transport"],
            url=runtime["url"], env=runtime["env"], headers=runtime["headers"],
        )
        try:
            await connection.connect()
            return await connection.read_resource(uri)
        except Exception as exc:
            raise ValueError(safe_error(exc, runtime["secret_values"])) from exc
        finally:
            await connection.close()

    def runtime_configs(self, *, all_agents: bool = False) -> list[dict]:
        with self.session_factory() as db:
            result = []
            for item in self.configs.list_auto_connect(db, all_agents=all_agents):
                config = _config_dict(item, self.configs)
                try:
                    result.append(self._runtime_config(config))
                except Exception as exc:
                    result.append(
                        {
                            **config,
                            "env": {},
                            "headers": {},
                            "secret_values": [],
                            "preflight_error": safe_error(exc),
                        }
                    )
            return result

    def persist_runtime_state(self, config_id: str, state: dict) -> None:
        with self.session_factory() as db:
            self.states.upsert(
                db,
                config_id,
                status=state.get("status", "stopped"),
                connected_at=_parse_datetime(state.get("connected_at")),
                last_success_at=_parse_datetime(state.get("last_success_at")),
                last_error_code=state.get("last_error_code"),
                last_error=state.get("last_error"),
                retry_count=int(state.get("retry_count", 0)),
                next_retry_at=_parse_datetime(state.get("next_retry_at")),
                server_info_json=json.dumps(state.get("server_info", {}), ensure_ascii=False),
                capabilities_json=json.dumps(state.get("capabilities", {}), ensure_ascii=False),
            )

    def _runtime_config(self, config: dict) -> dict:
        env = {key: os.environ[key] for key in BASE_CHILD_ENV if key in os.environ}
        env.update(config["env"])
        headers: dict[str, str] = {}
        secret_values: list[str] = []
        for key, ref in config["secret_refs"].items():
            value = self.secrets.get(ref)
            if not value:
                raise ValueError(f"MCP Secret 不可读取：{key}")
            secret_values.append(value)
            if key.startswith("env:"):
                env[key.removeprefix("env:")] = value
            elif key.startswith("header:"):
                headers[key.removeprefix("header:")] = value
        return {
            **config,
            "env": env,
            "headers": headers,
            "secret_values": secret_values,
        }

    def _summary(self, db, item) -> McpServerSummary:
        state = self.states.get(db, item.id)
        return McpServerSummary(
            id=item.id,
            name=item.name,
            transport=item.transport,
            command=item.command,
            args=self.configs.args(item),
            url=item.url,
            env_names=sorted(self.configs.json_field(item, "env_json")),
            secret_names=sorted(self.configs.json_field(item, "secret_refs_json")),
            tool_allowlist=self.configs.tool_allowlist(item),
            legacy_all_tools=item.legacy_all_tools,
            resource_allowlist=self.configs.json_field(item, "resource_allowlist_json"),
            prompt_allowlist=self.configs.json_field(item, "prompt_allowlist_json"),
            enabled=item.enabled,
            auto_connect=item.auto_connect,
            status=state.status if state else ("stopped" if not item.enabled else "unknown"),
            connected_at=_iso(state.connected_at) if state else None,
            last_success_at=_iso(state.last_success_at) if state else None,
            last_error=state.last_error if state else None,
            retry_count=state.retry_count if state else 0,
            next_retry_at=_iso(state.next_retry_at) if state else None,
            server_info=json.loads(state.server_info_json) if state and state.server_info_json else {},
            capabilities=json.loads(state.capabilities_json) if state and state.capabilities_json else {},
        )

    def _bump_revision(self, db) -> None:
        current = self.settings.get(db, CONFIG_REVISION_KEY) or 0
        self.settings.set(db, CONFIG_REVISION_KEY, int(current) + 1)

    @staticmethod
    def _validate_name(name: str) -> None:
        if not NAME_PATTERN.fullmatch(name):
            raise ValueError("MCP 名称只能包含字母、数字、点、下划线和连字符")

    @staticmethod
    def _validate_env_key(key: str) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key):
            raise ValueError("环境变量名无效")

    @staticmethod
    def _validate_url(transport: str, url: str | None) -> None:
        if not url:
            raise ValueError("HTTP MCP 必须提供 URL")
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("MCP URL 必须是 http(s) 地址")
        try:
            loopback = parsed.hostname.lower() == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname.lower() == "localhost"
        if parsed.scheme != "https" and not loopback:
            raise ValueError("非本机 MCP HTTP 必须使用 HTTPS")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("MCP URL 不能包含用户名、密码或片段")
        if any(key.lower() in SENSITIVE_QUERY_KEYS for key, _ in parse_qsl(parsed.query)):
            raise ValueError("MCP URL 不能携带 Token 或 API Key 查询参数")
        if transport == "sse" and not parsed.path:
            raise ValueError("SSE MCP 必须提供事件端点路径")


def _config_dict(item, repo: McpConfigRepository) -> dict:
    return {
        "id": item.id,
        "character_id": item.character_id,
        "name": item.name,
        "transport": item.transport or "stdio",
        "command": item.command,
        "args": repo.args(item),
        "url": item.url,
        "env": repo.json_field(item, "env_json"),
        "secret_refs": repo.json_field(item, "secret_refs_json"),
        "tool_allowlist": repo.tool_allowlist(item),
        "legacy_all_tools": bool(item.legacy_all_tools),
        "resource_allowlist": repo.json_field(item, "resource_allowlist_json"),
        "prompt_allowlist": repo.json_field(item, "prompt_allowlist_json"),
        "enabled": item.enabled,
        "auto_connect": item.auto_connect,
        "updated_at": _iso(item.updated_at),
    }


def _resource_allowed(uri: str, rule: str) -> bool:
    return uri.startswith(rule[:-1]) if rule.endswith("*") else uri == rule


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _parse_datetime(value: str | None):
    return datetime.fromisoformat(value) if value else None
