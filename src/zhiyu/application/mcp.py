"""MCP服务器持久化配置用例。"""

from __future__ import annotations

from dataclasses import dataclass

from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.integration_repository import (
    McpConfigRepository,
)


@dataclass(slots=True)
class McpServerSummary:
    name: str
    command: str
    args: list[str]
    tool_allowlist: list[str]
    enabled: bool
    auto_connect: bool


class McpService:
    def __init__(self, session_factory=SessionLocal) -> None:
        self.session_factory = session_factory
        self.configs = McpConfigRepository()

    def list(self) -> list[McpServerSummary]:
        with self.session_factory() as db:
            return [
                McpServerSummary(
                    name=item.name,
                    command=item.command,
                    args=self.configs.args(item),
                    tool_allowlist=self.configs.tool_allowlist(item),
                    enabled=item.enabled,
                    auto_connect=item.auto_connect,
                )
                for item in self.configs.list(db)
            ]

    def configure(
        self,
        name: str,
        command: str,
        args: list[str],
        tool_allowlist: list[str],
    ) -> McpServerSummary:
        if not name.strip() or not command.strip():
            raise ValueError("MCP名称和命令不能为空")
        with self.session_factory() as db:
            item = self.configs.upsert(
                db,
                name.strip(),
                command.strip(),
                args,
                tool_allowlist=tool_allowlist,
            )
            return McpServerSummary(
                name=item.name,
                command=item.command,
                args=self.configs.args(item),
                tool_allowlist=self.configs.tool_allowlist(item),
                enabled=item.enabled,
                auto_connect=item.auto_connect,
            )

    def disable(self, name: str) -> None:
        with self.session_factory() as db:
            if self.configs.get(db, name) is None:
                raise ValueError("MCP服务器不存在")
            self.configs.disable(db, name)
