"""Channel Manager：管理渠道适配器的连接状态。"""

import asyncio

from .base import ChannelAdapter
from .qq.adapter import QQAdapter
from .router import ChannelRouter


class ChannelManager:
    def __init__(self, router: ChannelRouter):
        self.router = router
        self._adapters: dict[str, ChannelAdapter] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def list(self) -> list[dict]:
        return [{"channel": "qq", "connected": "qq" in self._adapters}]

    async def connect(self, channel: str, ws_url: str, access_token: str | None = None) -> None:
        if channel != "qq":
            raise ValueError(f"未知渠道: {channel}")
        await self.disconnect(channel)
        adapter = QQAdapter(self.router, ws_url, access_token)
        self._adapters[channel] = adapter
        self._tasks[channel] = asyncio.create_task(adapter.start())

    async def disconnect(self, channel: str) -> None:
        adapter = self._adapters.pop(channel, None)
        if adapter is not None:
            await adapter.stop()
        task = self._tasks.pop(channel, None)
        if task is not None:
            task.cancel()


default_router = ChannelRouter()
default_manager = ChannelManager(default_router)
