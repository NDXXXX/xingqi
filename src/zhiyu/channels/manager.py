"""Channel Manager：管理渠道适配器的连接状态。"""

from datetime import datetime, timezone

from zhiyu.application.inbound import ChannelReliabilityService
from zhiyu.infrastructure.database.db import SessionLocal

from .base import ChannelAdapter
from .qq.adapter import QQAdapter
from .router import ChannelRouter


class ChannelManager:
    def __init__(self, router: ChannelRouter, session_factory=SessionLocal):
        self.router = router
        self.reliability = ChannelReliabilityService(session_factory)
        self._adapters: dict[str, ChannelAdapter] = {}
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
        adapter = self._adapters.get("qq")
        return [{"channel": "qq", "connected": state["status"] == "connected",
                 "ws_url": adapter.ws_url if adapter else None, **state}]

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

    async def connect(
        self,
        channel: str,
        ws_url: str,
        access_token: str | None = None,
        owner_user_id: str | None = None,
        allow_group_messages: bool = False,
        group_require_mention: bool = True,
    ) -> None:
        if channel != "qq":
            raise ValueError(f"未知渠道: {channel}")
        adapter = QQAdapter(
            self.router,
            ws_url,
            access_token,
            on_status=lambda status, error, retries: self._set_status(
                channel, status, error, retries
            ),
            owner_user_id=owner_user_id,
            allow_group_messages=allow_group_messages,
            group_require_mention=group_require_mention,
            reliability=self.reliability,
        )
        await self.disconnect(channel)
        await adapter.start()
        self._adapters[channel] = adapter

    async def disconnect(self, channel: str) -> None:
        adapter = self._adapters.pop(channel, None)
        if adapter is not None:
            await adapter.stop()
        self._set_status(channel, "disconnected")

    async def close_all(self) -> None:
        for channel in list(self._adapters):
            await self.disconnect(channel)


default_router = ChannelRouter()
default_manager = ChannelManager(default_router)
