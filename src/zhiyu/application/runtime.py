"""常驻进程共享的应用生命周期宿主。"""

import asyncio
import logging

from zhiyu.application.chat import ChatService
from zhiyu.application.channels import ChannelService
from zhiyu.channels.media import MediaStore
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
        channel_service: ChannelService | None = None,
        mcp_manager: McpManager | None = None,
        skill_registry: SkillRegistry = default_registry,
        auto_connect_mcp: bool = True,
        auto_connect_channels: bool = True,
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
        self.auto_connect_channels = auto_connect_channels and (
            channel_service is not None or isinstance(self.channel_manager, ChannelManager)
        )
        self.mcp_configs = McpConfigRepository()
        self.channel_service = channel_service or ChannelService(
            self.chat_service.session_factory, self.channel_manager
        )
        self.media_store = MediaStore(self.chat_service.session_factory)
        self._recovery_task: asyncio.Task | None = None
        self.channel_start_errors: list[str] = []
        self.started = False

    async def start(self) -> None:
        if self.started:
            return
        self.channel_start_errors.clear()
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
        if self.auto_connect_channels:
            try:
                await self.channel_service.start_auto_connect()
            except Exception as exc:
                message = str(exc)
                self.channel_start_errors.append(message)
                logger.warning("Channel auto-connect degraded: %s", message)
        self.chat_service.memory_processor.kick()
        self.started = True
        if getattr(type(self.channel_manager), "recover_once", None) is not None:
            self._recovery_task = asyncio.create_task(self._recovery_loop())

    async def stop(self) -> None:
        if not self.started:
            return
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            await asyncio.gather(self._recovery_task, return_exceptions=True)
            self._recovery_task = None
        await self.channel_manager.close_all()
        await self.mcp_manager.close_all()
        await self.chat_service.memory_processor.stop()
        self.started = False

    def health(self) -> dict:
        result = {
            "started": self.started,
            "channels": self.channel_manager.list(),
            "mcp_servers": self.mcp_manager.servers(),
            "memory_jobs": self.chat_service.memory_processor.status(),
        }
        if self.channel_start_errors:
            result["degraded"] = True
            result["channel_errors"] = list(self.channel_start_errors)
        return result

    async def _recovery_loop(self) -> None:
        cleanup_counter = 0
        while True:
            try:
                await self.channel_manager.recover_once()
                cleanup_counter += 1
                if cleanup_counter >= 720:
                    self.media_store.cleanup()
                    cleanup_counter = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Channel recovery sweep failed")
            await asyncio.sleep(5)

    async def __aenter__(self) -> "RuntimeHost":
        await self.start()
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        await self.stop()
