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
                "channel": "qq",
                "account_id": "qq-onebot-default",
                "channel_config_id": None,
                "status": "disconnected",
                "last_connected_at": None,
                "last_disconnected_at": None,
                "last_error": None,
                "retry_count": 0,
            }
        }

    def list(self) -> list[dict]:
        items = []
        for key, state in self._states.items():
            adapter = self._adapters.get(key)
            items.append(
                {
                    **state,
                    "connected": state["status"] == "connected",
                    "ws_url": adapter.ws_url if adapter else None,
                }
            )
        return items

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
        *,
        channel_config_id: str | None = None,
        account_id: str = "qq-onebot-default",
    ) -> None:
        if channel != "qq":
            raise ValueError(f"未知渠道: {channel}")
        key = channel_config_id or channel
        if key != channel and channel in self._states and channel not in self._adapters:
            self._states.pop(channel)
        self._states.setdefault(
            key,
            {
                "channel": channel,
                "account_id": account_id,
                "channel_config_id": channel_config_id,
                "status": "disconnected",
                "last_connected_at": None,
                "last_disconnected_at": None,
                "last_error": None,
                "retry_count": 0,
            },
        )
        adapter = QQAdapter(
            self.router,
            ws_url,
            access_token,
            on_status=lambda status, error, retries: self._set_status(
                key, status, error, retries
            ),
            owner_user_id=owner_user_id,
            allow_group_messages=allow_group_messages,
            group_require_mention=group_require_mention,
            channel_config_id=channel_config_id,
            account_id=account_id,
            reliability=self.reliability,
        )
        await self.disconnect(key)
        await adapter.start()
        self._adapters[key] = adapter

    async def disconnect(self, channel: str) -> None:
        key = channel
        if channel == "qq" and channel not in self._adapters:
            key = next(
                (item for item, state in self._states.items() if state.get("channel") == "qq"),
                channel,
            )
        adapter = self._adapters.pop(key, None)
        if adapter is not None:
            await adapter.stop()
        self._set_status(key, "disconnected")

    async def recover_once(self) -> int:
        recovered = 0
        for adapter in list(self._adapters.values()):
            recover = getattr(adapter, "recover_once", None)
            if recover is not None:
                recovered += await recover()
        return recovered

    async def close_all(self) -> None:
        for channel in list(self._adapters):
            await self.disconnect(channel)


default_router = ChannelRouter()
default_manager = ChannelManager(default_router)
