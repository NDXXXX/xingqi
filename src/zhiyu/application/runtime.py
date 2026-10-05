"""常驻进程共享的应用生命周期宿主。"""

import logging

from zhiyu.application.chat import ChatService
from zhiyu.channels.manager import ChannelManager
from zhiyu.channels.router import ChannelRouter
from zhiyu.integrations.mcp.manager import McpManager
from zhiyu.integrations.skills.registry import SkillRegistry, default_registry
from zhiyu.infrastructure.database.repositories.integration_repository import (
    McpConfigRepository,
)


logger = logging.getLogger(__name__)


class RuntimeHost:
    def __init__(
        self,
        *,
        chat_service: ChatService | None = None,
        channel_manager: ChannelManager | None = None,
        mcp_manager: McpManager | None = None,
        skill_registry: SkillRegistry = default_registry,
        auto_connect_mcp: bool = True,
    ) -> None:
        self.chat_service = chat_service or ChatService()
        self.channel_manager = channel_manager or ChannelManager(
            ChannelRouter(self.chat_service),
            self.chat_service.session_factory,
        )
        self.mcp_manager = mcp_manager or self.chat_service.mcp_manager
        self.chat_service.mcp_manager = self.mcp_manager
        self.skill_registry = skill_registry
        self.auto_connect_mcp = auto_connect_mcp
        self.mcp_configs = McpConfigRepository()
        self.started = False

    async def start(self) -> None:
        if self.started:
            return
        self.skill_registry.reload()
        if self.auto_connect_mcp:
            with self.chat_service.session_factory() as db:
                configs = [
                    (
                        item.name,
                        item.command,
                        self.mcp_configs.args(item),
                        self.mcp_configs.tool_allowlist(item),
                    )
                    for item in self.mcp_configs.list_auto_connect(db)
                ]
            for name, command, args, allowlist in configs:
                try:
                    await self.mcp_manager.connect_with_retry(
                        name,
                        command,
                        args,
                        tool_allowlist=allowlist,
                    )
                except Exception as exc:
                    logger.warning("MCP server %s failed to connect: %s", name, exc)
        self.chat_service.memory_processor.kick()
        self.started = True

    async def stop(self) -> None:
        if not self.started:
            return
        await self.channel_manager.close_all()
        await self.mcp_manager.close_all()
        await self.chat_service.memory_processor.stop()
        self.started = False

    def health(self) -> dict:
        return {
            "started": self.started,
            "channels": self.channel_manager.list(),
            "mcp_servers": self.mcp_manager.servers(),
            "memory_jobs": self.chat_service.memory_processor.status(),
        }

    async def __aenter__(self) -> "RuntimeHost":
        await self.start()
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        await self.stop()
