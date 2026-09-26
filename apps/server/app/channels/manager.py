"""Channel Manager：管理渠道适配器的连接状态。"""

import asyncio
from contextlib import suppress
from datetime import datetime, timezone

from .base import ChannelAdapter
from .qq.adapter import QQAdapter
from .router import ChannelRouter


class ChannelManager:
    def __init__(self, router: ChannelRouter):
        self.router = router
        self._adapters: dict[str, ChannelAdapter] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._states: dict[str, dict] = {
            "qq": {
                "status": "disconnected",
                "last_connected_at": None,
                "last_disconnected_at": None,
                "last_error": None,
                "retry_count": 0,
            }
        }

    def list(self) -> list[dict]:
        state = self._states["qq"]
        return [{"channel": "qq", "connected": state["status"] == "connected", **state}]

    def _set_status(
        self, channel: str, status: str, error: str | None = None, retries: int = 0
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        state = self._states.setdefault(channel, {})
        state.update(status=status, last_error=error, retry_count=retries)
        if status == "connected":
            state["last_connected_at"] = now
        elif status == "disconnected":
            state["last_disconnected_at"] = now

    async def connect(self, channel: str, ws_url: str, access_token: str | None = None) -> None:
        if channel != "qq":
            raise ValueError(f"未知渠道: {channel}")
        await self.disconnect(channel)
        self._set_status(channel, "connecting")
        adapter = QQAdapter(
            self.router,
            ws_url,
            access_token,
            lambda status, error, retries: self._set_status(
                channel, status, error, retries
            ),
        )
        self._adapters[channel] = adapter
        self._tasks[channel] = asyncio.create_task(adapter.start())

    async def disconnect(self, channel: str) -> None:
        adapter = self._adapters.pop(channel, None)
        if adapter is not None:
            await adapter.stop()
        task = self._tasks.pop(channel, None)
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._set_status(channel, "disconnected")

    async def close_all(self) -> None:
        for channel in list(self._adapters):
            await self.disconnect(channel)


default_router = ChannelRouter()
default_manager = ChannelManager(default_router)
